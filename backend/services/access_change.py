"""Credential changes verified by an SSH login before they take effect.

A change of the SSH credential a host is reached with — its own credential, the
credential of its group, or a move to a group with another credential — first
logs in to every affected host with the new credential. Hosts where the login
fails keep their previous access:

- set_host_credential: the host keeps its credential;
- move_to_group: the host stays in its group;
- set_group_credential: the group gets the new credential, and each failed host
  is pinned to the credential it used before (as its own credential).

Hosts whose effective credential does not change are applied without a check.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from celery_app import celery_app
from database import SessionLocal
from models.credential import Credential
from models.host import Host, HostGroup
from models.task import TaskRun, TaskStatus
from services.ansible_runner import build_full_inventory, credential_vars, run_ansible
from services.host_diagnostic_utils import sanitize_detail

logger = logging.getLogger(__name__)

SET_HOST_CREDENTIAL = "set_host_credential"
SET_GROUP_CREDENTIAL = "set_group_credential"
MOVE_TO_GROUP = "move_to_group"
ACTIONS = (SET_HOST_CREDENTIAL, SET_GROUP_CREDENTIAL, MOVE_TO_GROUP)

CHECK_COMMAND = "echo fleet-access-ok"


# ---------- plan (pure functions over plain ids) ----------

def effective_credential(own_id, group_id, groups: dict):
    """Credential SSH uses: the host's own, otherwise the nearest group credential up
    the tree. groups maps group id -> (parent_id, credential_id)."""
    if own_id:
        return own_id
    seen = set()
    while group_id and group_id in groups and group_id not in seen:
        seen.add(group_id)
        parent_id, credential_id = groups[group_id]
        if credential_id:
            return credential_id
        group_id = parent_id
    return None


def in_subtree(group_id, root_id, groups: dict) -> bool:
    seen = set()
    while group_id and group_id not in seen:
        if group_id == root_id:
            return True
        seen.add(group_id)
        group_id = groups.get(group_id, (None, None))[0]
    return False


@dataclass
class HostPlan:
    host_id: object
    old_credential: object  # effective credential before the change (None: no access configured)
    new_credential: object  # effective credential after it
    needs_check: bool
    skip_reason: str | None = None  # the change does not apply to this host at all


def plan_host_credential(hosts, credential_id, groups: dict, agent_key_ids: set) -> list[HostPlan]:
    """hosts: (id, own_credential_id, group_id). credential_id None means "as the group"."""
    plans = []
    for host_id, own, group_id in hosts:
        old = effective_credential(own, group_id, groups)
        if own in agent_key_ids:
            plans.append(HostPlan(host_id, old, old, False, "подключается ключом агента, он не меняется"))
            continue
        new = effective_credential(credential_id, group_id, groups)
        plans.append(HostPlan(host_id, old, new, new != old))
    return plans


def plan_move(hosts, target_group_id, groups: dict) -> list[HostPlan]:
    """target_group_id None: out of any group (a new group by name has no credential either)."""
    plans = []
    for host_id, own, group_id in hosts:
        old = effective_credential(own, group_id, groups)
        new = effective_credential(own, target_group_id, groups)
        plans.append(HostPlan(host_id, old, new, new != old))
    return plans


def plan_group_credential(hosts, group_id, credential_id, groups: dict) -> list[HostPlan]:
    """Only hosts below the group whose effective credential changes are affected."""
    changed = dict(groups)
    parent_id, _ = groups[group_id]
    changed[group_id] = (parent_id, credential_id)
    plans = []
    for host_id, own, host_group in hosts:
        if not in_subtree(host_group, group_id, groups):
            continue
        old = effective_credential(own, host_group, groups)
        new = effective_credential(own, host_group, changed)
        if new != old:
            plans.append(HostPlan(host_id, old, new, True))
    return plans


def needs_verification(plans: list[HostPlan]) -> bool:
    return any(p.needs_check for p in plans)


# ---------- database ----------

def load_groups(db) -> dict:
    return {gid: (parent, cred) for gid, parent, cred in db.execute(select(HostGroup.id, HostGroup.parent_id, HostGroup.credential_id)).all()}


def agent_key_ids(db) -> set:
    return set(db.execute(select(Credential.id).where(Credential.is_agent_managed.is_(True))).scalars().all())


def host_rows(db, host_ids=None):
    query = select(Host.id, Host.credential_id, Host.group_id)
    if host_ids is not None:
        query = query.where(Host.id.in_(host_ids))
    return db.execute(query).all()


def hosts_by_ids(db, host_ids) -> list[Host]:
    if not host_ids:
        return []
    return db.execute(select(Host).where(Host.id.in_(host_ids))).scalars().all()


def build_plan(db, spec: dict) -> list[HostPlan]:
    groups = load_groups(db)
    action = spec["action"]
    if action == SET_HOST_CREDENTIAL:
        return plan_host_credential(host_rows(db, _uuids(spec["host_ids"])), _uuid(spec.get("credential_id")), groups, agent_key_ids(db))
    if action == MOVE_TO_GROUP:
        return plan_move(host_rows(db, _uuids(spec["host_ids"])), _uuid(spec.get("group_id")), groups)
    if action == SET_GROUP_CREDENTIAL:
        return plan_group_credential(host_rows(db), _uuid(spec["group_id"]), _uuid(spec.get("credential_id")), groups)
    raise ValueError(f"unknown action {action}")


def apply_change(db, spec: dict, plans: list[HostPlan], passed: set) -> dict:
    """Applies the change to unaffected hosts and to hosts whose login passed.
    Returns counters and the hosts left as they were."""
    action = spec["action"]
    ok_ids = [p.host_id for p in plans if p.skip_reason is None and (not p.needs_check or p.host_id in passed)]
    failed = [p for p in plans if p.needs_check and p.host_id not in passed]
    pinned = 0
    unchanged = 0  # вход не прошёл, но и раньше учётки не было: вернуть «без учётки» нельзя

    if action == SET_HOST_CREDENTIAL:
        credential_id = _uuid(spec.get("credential_id"))
        for host in hosts_by_ids(db, ok_ids):
            host.credential_id = credential_id
    elif action == MOVE_TO_GROUP:
        target_id = _uuid(spec.get("group_id"))
        if ok_ids and spec.get("group_name") and target_id is None:
            from services.host_grouping import find_group_by_name

            group = find_group_by_name(db, spec["group_name"])
            if group is None:
                group = HostGroup(name=spec["group_name"])
                db.add(group)
                db.flush()
            target_id = group.id
        for host in hosts_by_ids(db, ok_ids):
            host.group_id = target_id
    elif action == SET_GROUP_CREDENTIAL:
        group = db.get(HostGroup, _uuid(spec["group_id"]))
        group.credential_id = _uuid(spec.get("credential_id"))
        # Хост, на котором вход не прошёл, остаётся на прежней учётке: она становится его собственной
        for plan in failed:
            if plan.old_credential is None:
                unchanged += 1
                continue
            host = db.get(Host, plan.host_id)
            if host is not None and host.credential_id is None:
                host.credential_id = plan.old_credential
                pinned += 1
    db.commit()
    return {"applied": len(ok_ids), "failed": len(failed), "pinned": pinned, "without_previous": unchanged}


# ---------- verification ----------

def verify_logins(db, plans: list[HostPlan]) -> dict:
    """Logs in to every host that needs a check with its new credential.
    Returns host_id -> None (ok) or an error message."""
    to_check = [p for p in plans if p.needs_check]
    results: dict = {}
    without_credential = [p for p in to_check if p.new_credential is None]
    for plan in without_credential:
        results[plan.host_id] = "после смены у ПК не останется учётных данных"
    checkable = [p for p in to_check if p.new_credential is not None]
    if not checkable:
        return results

    credentials = {c.id: c for c in db.execute(select(Credential).where(Credential.id.in_({p.new_credential for p in checkable}))).scalars().all()}
    inventory = build_full_inventory(db, [p.host_id for p in checkable])
    secrets = []
    for plan in checkable:
        credential = credentials.get(plan.new_credential)
        host_vars = inventory["all"]["children"]["Win_Hosts"]["hosts"].get(str(plan.host_id))
        if host_vars is None or credential is None:
            results[plan.host_id] = "хост или учётка не найдены"
            continue
        # Подставляется новая учётка вместо действующей
        for key in ("ansible_user", "ansible_password", "ansible_ssh_private_key_file"):
            host_vars.pop(key, None)
        new_vars = credential_vars(credential)
        host_vars.update(new_vars)
        if new_vars.get("ansible_password"):
            secrets.append(new_vars["ansible_password"])

    result = run_ansible(module="ansible.builtin.raw", module_args=CHECK_COMMAND, host_pattern="all", inventory=inventory, quiet=True)
    by_key = {str(p.host_id): p.host_id for p in checkable}
    for event in result.events:
        event_data = event.get("event_data", {})
        host_id = by_key.get(event_data.get("host"))
        if host_id is None:
            continue
        res = event_data.get("res") or {}
        if event.get("event") == "runner_on_ok" and res.get("rc", 1) == 0:
            results[host_id] = None
        elif event.get("event") in ("runner_on_unreachable", "runner_on_failed"):
            results[host_id] = sanitize_detail(str(res.get("msg") or res.get("stderr") or event.get("event")), secrets)[:300]
    for plan in checkable:
        results.setdefault(plan.host_id, "нет ответа от Ansible")
    return results


ACTION_TITLES = {
    SET_HOST_CREDENTIAL: "Смена учётных данных хостов",
    SET_GROUP_CREDENTIAL: "Смена учётных данных группы",
    MOVE_TO_GROUP: "Перенос хостов в группу",
}


@celery_app.task(name="services.access_change.run_access_change")
def run_access_change(task_run_id: str):
    db = SessionLocal()
    task = None
    try:
        task = db.get(TaskRun, uuid.UUID(task_run_id))
        if task is None:
            return
        task.status = TaskStatus.running
        task.started_at = datetime.now(timezone.utc)
        task.log_output = ""
        db.commit()
        spec = task.extra_vars or {}

        plans = build_plan(db, spec)
        labels = dict(db.execute(select(Host.id, Host.hostname)).all())
        credential_names = dict(db.execute(select(Credential.id, Credential.name)).all())
        label = lambda host_id: labels.get(host_id) or str(host_id)  # noqa: E731
        name = lambda cred: f"«{credential_names.get(cred, cred)}»" if cred else "без учётных данных"  # noqa: E731

        checks = [p for p in plans if p.needs_check]
        _log(db, task, f"{ACTION_TITLES.get(spec.get('action'), 'Смена доступа')}: учётка меняется у {len(checks)} ПК, проверяем вход новыми данными")
        results = verify_logins(db, plans)
        passed = {host_id for host_id, error in results.items() if error is None}
        for plan in checks:
            error = results.get(plan.host_id)
            if error is None:
                _log(db, task, f"[{label(plan.host_id)}] вход с {name(plan.new_credential)} — успешно")
            else:
                _log(db, task, f"[{label(plan.host_id)}] вход с {name(plan.new_credential)} не удался: {error}; остаётся {name(plan.old_credential)}")
        for plan in plans:
            if plan.skip_reason:
                _log(db, task, f"[{label(plan.host_id)}] пропущен: {plan.skip_reason}")

        summary = apply_change(db, spec, plans, passed)
        line = f"Применено на {summary['applied']} ПК, не применено на {summary['failed']}"
        if summary["pinned"]:
            line += f"; {summary['pinned']} ПК оставлены на прежней учётке (назначена им напрямую)"
        if summary.get("without_previous"):
            line += f"; у {summary['without_previous']} ПК учётки не было и раньше — им достаётся учётка группы"
        _log(db, task, line)
        task.status = TaskStatus.failed if summary["failed"] else TaskStatus.success
        task.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("access change %s failed", task_run_id)
        db.rollback()
        if task is not None:
            _log(db, task, f"ОШИБКА: {exc}. Изменения не применены")
            task.status = TaskStatus.failed
            task.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def _log(db, task: TaskRun, message: str) -> None:
    task.log_output = f"{task.log_output}{message}\n"
    db.commit()


def _uuid(value):
    if value is None or value == "":
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _uuids(values):
    return [_uuid(v) for v in values or []]
