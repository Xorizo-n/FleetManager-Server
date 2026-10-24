"""Обработка хостов задачи сразу на нескольких ПК.

Обновление агента, проверка его версии и сканирование ПО выполняют по SSH
команды на каждом ПК отдельно; почти всё это время сервер ждёт ПК. Поэтому
хосты обрабатываются пачкой — settings.host_task_parallelism одновременно,
у каждого потока своя сессия БД. Плейбуки сюда не относятся: их параллелит
сам Ansible (ANSIBLE_FORKS).

Строки журнала дописываются в task_runs.log_output одним UPDATE в базе, а не
присваиванием в ORM — иначе потоки затирали бы строки друг друга.
"""

import enum
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import case, update

from config import settings
from database import SessionLocal
from models.host import Host
from models.task import TaskRun


class HostOutcome(str, enum.Enum):
    ok = "ok"
    # Недоступен по сети: задача неуспешна, но о самой операции это ничего не говорит
    unreachable = "unreachable"
    failed = "failed"


def append_task_log(db, task_id: uuid.UUID, message: str) -> None:
    """Дописывает строку в журнал задачи атомарно и сразу фиксирует её."""
    db.execute(
        update(TaskRun)
        .where(TaskRun.id == task_id)
        .values(log_output=case(
            (TaskRun.log_output.is_(None), message),
            (TaskRun.log_output == "", message),
            else_=TaskRun.log_output + "\n" + message,
        ))
        .execution_options(synchronize_session=False)
    )
    db.commit()


def host_label(host: Host) -> str:
    return host.hostname or host.ip_address or str(host.id)


def run_for_hosts(
    task_id: uuid.UUID,
    host_ids: Sequence[uuid.UUID],
    worker: Callable[[object, Host], HostOutcome],
    *,
    canary: bool = False,
    parallelism: int | None = None,
    session_factory: Callable[[], object] = SessionLocal,
) -> bool:
    """Вызывает worker(db, host) для каждого хоста; True — хотя бы один не ок.

    Итог по каждому ПК пишется в host_states задачи: success, failed (в том числе
    недоступен) или cancelled — не тронут, потому что остановился canary.

    canary: хосты сначала идут по одному, пока какой-то не ответит по существу.
    Если первая настоящая попытка провалилась, остальные не трогаются — неудачный
    релиз агента ломает один ПК, а не пачку. Недоступные ПК проверкой не считаются.
    """

    def one(host_id: uuid.UUID) -> HostOutcome:
        db = session_factory()
        try:
            host = db.get(Host, host_id)
            if host is None:
                return HostOutcome.ok
            try:
                return worker(db, host)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                append_task_log(db, task_id, f"[{host_label(host)}] ОШИБКА: {exc}")
                return HostOutcome.failed
        finally:
            db.close()

    remaining = list(host_ids)
    outcomes: dict[uuid.UUID, HostOutcome] = {}
    if canary:
        while remaining:
            host_id = remaining.pop(0)
            outcome = outcomes[host_id] = one(host_id)
            if outcome == HostOutcome.ok:
                break
            if outcome == HostOutcome.failed:
                db = session_factory()
                try:
                    if remaining:
                        append_task_log(db, task_id, f"Первый ПК не прошёл — остальные ({len(remaining)}) не тронуты, чтобы не повторить ошибку на всех")
                    _store_outcomes(db, task_id, outcomes, untouched=remaining)
                finally:
                    db.close()
                return True

    if remaining:
        workers = max(1, min(parallelism or settings.host_task_parallelism, len(remaining)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="host") as pool:
            outcomes.update(zip(remaining, pool.map(one, remaining)))
    db = session_factory()
    try:
        _store_outcomes(db, task_id, outcomes, untouched=[])
    finally:
        db.close()
    return any(outcome != HostOutcome.ok for outcome in outcomes.values())


def _store_outcomes(db, task_id: uuid.UUID, outcomes: dict, untouched: Sequence[uuid.UUID]) -> None:
    states = {str(h): "success" if o == HostOutcome.ok else "failed" for h, o in outcomes.items()}
    states.update({str(h): "cancelled" for h in untouched})
    db.execute(update(TaskRun).where(TaskRun.id == task_id).values(host_states=states).execution_options(synchronize_session=False))
    db.commit()
