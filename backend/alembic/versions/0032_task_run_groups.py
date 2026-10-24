"""one task per launch with per-host states; fold old per-host waiting tasks into launches

Revision ID: 0032_task_run_groups
Revises: 0031_grouped_waiting_tasks

До этой миграции выключенные ПК получали отдельные задачи (по одной на ПК, с 0031 —
одну ожидающую задачу и дочерние на пачки). Здесь задачи одного запуска (тот же
тип, плейбук, переменные, автор и минута создания) собираются в запуск: ожидающая
задача, если она есть, сама становится запуском, иначе запуск создаётся; остальные
задачи запуска становятся его дочерними (parent_id) и из списка задач пропадают.
"""

import json
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032_task_run_groups"
down_revision: Union[str, None] = "0031_grouped_waiting_tasks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFERRABLE = ("playbook", "software_scan", "agent_version_scan", "agent_update")
OPEN = {"waiting", "ready", "pending", "queued", "running"}
# Статус задачи -> состояние её ПК в запуске
HOST_STATE = {"success": "success", "failed": "failed", "cancelled": "cancelled", "queued": "queued",
              "running": "running", "pending": "pending", "waiting": "cancelled", "released": "cancelled"}


# Итог по ПК прошлых задач восстанавливается из журнала: у плейбука — PLAY RECAP
# (хосты в инвентаре названы своим id), у остальных — строки «[ПК] …» успешного исхода
RECAP = re.compile(r"^(\S+)\s+:\s+ok=\d+\s+changed=\d+\s+unreachable=(\d+)\s+failed=(\d+)", re.M)
SUCCESS_MARK = {
    "agent_update": re.compile(r"^\[([^\]]+)\] обновлено:", re.M),
    "agent_version_scan": re.compile(r"^\[([^\]]+)\] (?:версия |агент не найден)", re.M),
    "software_scan": re.compile(r"^\[([^\]]+)\] обнаружено пакетов", re.M),
}
TERMINAL = {"success", "failed", "cancelled"}


def _result_states(row, labels: dict) -> dict:
    """Итог по каждому ПК завершённой задачи; если журнал ничего не говорит — её статус для всех."""
    host_ids = json.loads(row["host_ids"])
    fallback = HOST_STATE.get(row["status"], "failed")
    if row["status"] != "failed":
        return {h: fallback for h in host_ids}
    log = row["log_output"]
    if row["task_type"] == "playbook":
        recap = {m.group(1): int(m.group(2)) + int(m.group(3)) for m in RECAP.finditer(log)}
        if not recap:
            return {h: fallback for h in host_ids}
        return {h: "success" if recap.get(h) == 0 else "failed" for h in host_ids}
    mark = SUCCESS_MARK.get(row["task_type"])
    if mark is None:
        return {h: fallback for h in host_ids}
    ok = {labels.get(label) for label in mark.findall(log)}
    return {h: "success" if h in ok else "failed" for h in host_ids}


def _group_status(states: dict) -> str:
    values = set(states.values())
    for status, members in (("running", {"running"}), ("queued", {"queued", "ready"}), ("pending", {"pending"}),
                            ("waiting", {"waiting"}), ("failed", {"failed"}), ("success", {"success"})):
        if values & members:
            return status
    return "cancelled"


def upgrade() -> None:
    op.add_column("task_runs", sa.Column("grouped", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("task_runs", sa.Column("host_states", sa.JSON(), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "select id, task_type::text task_type, repo_id, playbook_name, coalesce(extra_vars::text, '') ev, created_by, run_as_user_id,"
        " date_trunc('minute', created_at) created_minute, created_at, started_at, finished_at, status::text status,"
        " host_ids::text host_ids, coalesce(ready_host_ids::text, '[]') ready, coalesce(log_output, '') log_output, parent_id"
        " from task_runs where task_type::text in :types order by created_at"
    ).bindparams(sa.bindparam("types", expanding=True)), {"types": list(DEFERRABLE)}).mappings().all()

    # Подпись ПК в журнале (host_label: имя, иначе адрес) -> id
    labels = {}
    for host_id, hostname, ip in conn.execute(sa.text("select id::text, hostname, ip_address from hosts")):
        labels[hostname or ip or host_id] = host_id

    results = {}
    for row in rows:
        if row["status"] in TERMINAL:
            results[row["id"]] = _result_states(row, labels)
            conn.execute(sa.text("update task_runs set host_states = cast(:states as json) where id = :id"),
                         {"states": json.dumps(results[row["id"]]), "id": row["id"]})

    def outcome(row) -> dict:
        return results.get(row["id"]) or {h: HOST_STATE.get(row["status"], "failed") for h in json.loads(row["host_ids"])}

    children = defaultdict(list)  # дочерние задачи пачек (0031)
    clusters = defaultdict(list)
    for row in rows:
        if row["parent_id"] is not None:
            children[row["parent_id"]].append(row)
        else:
            key = (row["task_type"], row["repo_id"], row["playbook_name"], row["ev"], row["created_by"], row["created_minute"])
            clusters[key].append(row)

    now = datetime.now(timezone.utc)
    for members in clusters.values():
        holders = [m for m in members if m["status"] in ("waiting", "released")]
        deferred = holders or [m for m in members if m["log_output"].startswith("ПК не в сети")]
        if not deferred or (len(members) == 1 and not holders):
            continue  # обычная задача, не запуск с выключенными ПК

        root = holders[0] if holders else None
        root_id = root["id"] if root else uuid.uuid4()
        states: dict[str, str] = {}
        hosts: list[str] = []

        def put(host_list, state):
            for h in host_list:
                if h not in states:
                    hosts.append(h)
                states[h] = state

        def put_outcome(row):
            for h, state in outcome(row).items():
                put([h], state)

        attached = []
        for m in members:
            if m is root:
                continue
            put_outcome(m)
            attached.append(m)
        for holder in holders:
            for child in children.get(holder["id"], []):
                put_outcome(child)
                attached.append(child)
        for holder in holders[1:]:
            put(json.loads(holder["host_ids"]), "cancelled")
        if root is not None:
            put(json.loads(root["ready"]), "ready")
            put(json.loads(root["host_ids"]), "waiting")

        status = _group_status(states)
        started = [m["started_at"] for m in attached if m["started_at"]]
        finished = [m["finished_at"] for m in attached if m["finished_at"]]
        finished_at = None if set(states.values()) & OPEN else (max(finished) if finished else now)
        params = {
            "id": root_id, "hosts": json.dumps(hosts), "states": json.dumps(states), "status": status,
            "started": min(started) if started else None, "finished": finished_at,
        }
        if root is not None:
            conn.execute(sa.text(
                "update task_runs set grouped = true, host_ids = cast(:hosts as json), host_states = cast(:states as json),"
                " status = cast(:status as taskstatus), started_at = :started, finished_at = :finished where id = :id"
            ), params)
        else:
            first = members[0]
            conn.execute(sa.text(
                "insert into task_runs (id, task_type, repo_id, playbook_name, extra_vars, host_ids, host_states, status, grouped,"
                " created_by, run_as_user_id, created_at, started_at, finished_at, log_output)"
                " select :id, task_type, repo_id, playbook_name, extra_vars, cast(:hosts as json), cast(:states as json),"
                " cast(:status as taskstatus), true, created_by, run_as_user_id, created_at, :started, :finished, :log"
                " from task_runs where id = :first"
            ), {**params, "first": first["id"], "log": f"Собран из {len(members)} задач этого запуска (по одной на ПК)."})
        for m in attached:
            conn.execute(sa.text("update task_runs set parent_id = :root where id = :id"), {"root": root_id, "id": m["id"]})
        # Лишние ожидающие задачи того же запуска: их ПК теперь ждёт сам запуск
        for holder in holders[1:]:
            conn.execute(sa.text(
                "update task_runs set parent_id = :root, status = 'cancelled', finished_at = :now where id = :id"
            ), {"root": root_id, "id": holder["id"], "now": now})

    op.drop_column("task_runs", "ready_host_ids")
    op.create_index("ix_task_runs_open_groups", "task_runs", ["created_at"],
                    postgresql_where=sa.text("grouped and finished_at is null"))


def downgrade() -> None:
    op.drop_index("ix_task_runs_open_groups", table_name="task_runs")
    op.add_column("task_runs", sa.Column("ready_host_ids", sa.JSON(), nullable=True))
    op.drop_column("task_runs", "host_states")
    op.drop_column("task_runs", "grouped")
