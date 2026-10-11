"""Задачи для выключенных ПК: ждут, пока ПК появится в сети.

При запуске плейбука, сканирования ПО или обслуживания агента ПК, которые
сейчас не в сети, не попадают в общую задачу: на каждый такой ПК создаётся своя
задача в статусе waiting. Она уходит в очередь, как только ПК пришлёт heartbeat
или ответит на проверку по SSH (у ПК без агента heartbeat нет), а если ПК не
появился за settings.waiting_task_ttl_days, отменяется.

Задача на один ПК, а не одна на всех: у каждого ПК свой результат, и отложенную
задачу можно отменить отдельно.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import cast, select, update
from sqlalchemy.dialects.postgresql import JSONB

from celery_app import celery_app
from config import settings
from database import SessionLocal
from models.host import Host, HostStatus
from models.task import TaskRun, TaskStatus, TaskType

# Задачи, которые имеет смысл выполнить позже. Диагностика нужна сейчас, а смена
# учётных данных проверяет вход сразу и применяется целиком.
DEFERRABLE_TYPES = frozenset({TaskType.playbook, TaskType.software_scan, TaskType.agent_version_scan, TaskType.agent_update})

# Пауза между heartbeat и запуском: агент стартует через пару минут после
# загрузки, sshd к этому времени уже работает, но пусть сеть окончательно поднимется.
RELEASE_DELAY_SECONDS = 15


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _celery_task(task_type: TaskType):
    # Импорт внутри: модули задач сами импортируют модели и ansible_runner
    if task_type == TaskType.playbook:
        from services.ansible_runner import run_playbook_task
        return run_playbook_task
    if task_type == TaskType.software_scan:
        from services.software_scanner import scan_software_task
        return scan_software_task
    if task_type == TaskType.agent_version_scan:
        from services.agent_update import run_agent_version_scan
        return run_agent_version_scan
    if task_type == TaskType.agent_update:
        from services.agent_update import run_agent_update
        return run_agent_update
    raise ValueError(f"task type {task_type} cannot be queued here")


def enqueue(task: TaskRun, countdown: int | None = None) -> None:
    _celery_task(task.task_type).apply_async(args=[str(task.id)], countdown=countdown)


def split_offline(db, host_ids: list[str]) -> tuple[list[str], list[str]]:
    """(в сети, не в сети). Хост, которого нет в реестре, идёт в сеть — задача сама сообщит об ошибке."""
    known = {str(host_id): status for host_id, status in db.execute(
        select(Host.id, Host.status).where(Host.id.in_([uuid.UUID(h) for h in host_ids]))
    ).all()}
    online = [h for h in host_ids if known.get(h, HostStatus.online) == HostStatus.online]
    offline = [h for h in host_ids if known.get(h, HostStatus.online) != HostStatus.online]
    return online, offline


def _existing_waiting(db, task_type: TaskType, host_id: str, fields: dict) -> TaskRun | None:
    """Та же задача на этот ПК уже ждёт — повторное нажатие её не дублирует."""
    candidates = db.execute(
        select(TaskRun).where(
            TaskRun.status == TaskStatus.waiting,
            TaskRun.task_type == task_type,
            cast(TaskRun.host_ids, JSONB).contains([host_id]),
        )
    ).scalars().all()
    for task in candidates:
        if all(getattr(task, key) == value for key, value in fields.items()):
            return task
    return None


def create_task_runs(
    db,
    *,
    task_type: TaskType,
    host_ids: list[str],
    created_by: uuid.UUID | None,
    defer_offline: bool = True,
    **fields,
) -> tuple[TaskRun | None, list[TaskRun]]:
    """Задача для ПК в сети и ожидающие задачи для выключенных. Сохраняет, но не запускает:
    задачу для ПК в сети вызывающий отправляет в celery сам (enqueue)."""
    if defer_offline and task_type in DEFERRABLE_TYPES:
        online, offline = split_offline(db, host_ids)
    else:
        online, offline = host_ids, []

    now_task = None
    if online:
        now_task = TaskRun(task_type=task_type, host_ids=online, status=TaskStatus.queued, created_by=created_by, **fields)
        db.add(now_task)

    deadline = _now() + timedelta(days=settings.waiting_task_ttl_days)
    waiting: list[TaskRun] = []
    for host_id in offline:
        existing = _existing_waiting(db, task_type, host_id, fields)
        if existing is not None:
            waiting.append(existing)
            continue
        task = TaskRun(
            task_type=task_type,
            host_ids=[host_id],
            status=TaskStatus.waiting,
            created_by=created_by,
            log_output=f"ПК не в сети. Задача запустится, когда он появится, но не позже {deadline:%d.%m.%Y %H:%M} UTC.",
            **fields,
        )
        db.add(task)
        waiting.append(task)

    db.commit()
    for task in ([now_task] if now_task else []) + waiting:
        db.refresh(task)
    return now_task, waiting


def release_waiting_tasks(db, host_id: uuid.UUID, reason: str = "heartbeat") -> int:
    """ПК появился в сети: его ожидающие задачи уходят в очередь. Возвращает их число.

    Статус меняется условным UPDATE, поэтому heartbeat и проверка по SSH,
    пришедшие одновременно, не запустят задачу дважды.
    """
    task_ids = db.execute(
        select(TaskRun.id).where(
            TaskRun.status == TaskStatus.waiting,
            cast(TaskRun.host_ids, JSONB).contains([str(host_id)]),
        )
    ).scalars().all()

    released = 0
    for task_id in task_ids:
        claimed = db.execute(
            update(TaskRun)
            .where(TaskRun.id == task_id, TaskRun.status == TaskStatus.waiting)
            .values(status=TaskStatus.queued)
        ).rowcount
        db.commit()
        if not claimed:
            continue
        task = db.get(TaskRun, task_id)
        line = f"ПК появился в сети ({reason}, {_now():%d.%m.%Y %H:%M} UTC), задача запущена."
        task.log_output = f"{task.log_output}\n{line}" if task.log_output else line
        db.commit()
        enqueue(task, countdown=RELEASE_DELAY_SECONDS)
        released += 1
    return released


def cancel_waiting_task(db, task: TaskRun, reason: str) -> bool:
    claimed = db.execute(
        update(TaskRun)
        .where(TaskRun.id == task.id, TaskRun.status == TaskStatus.waiting)
        .values(status=TaskStatus.cancelled, finished_at=_now())
    ).rowcount
    db.commit()
    if claimed:
        db.refresh(task)
        task.log_output = f"{task.log_output}\n{reason}" if task.log_output else reason
        db.commit()
    return bool(claimed)


@celery_app.task(name="services.waiting_tasks.expire_waiting_tasks")
def expire_waiting_tasks() -> int:
    """Отменяет задачи, чей ПК не появился в сети за settings.waiting_task_ttl_days."""
    db = SessionLocal()
    try:
        cutoff = _now() - timedelta(days=settings.waiting_task_ttl_days)
        stale = db.execute(
            select(TaskRun).where(TaskRun.status == TaskStatus.waiting, TaskRun.created_at < cutoff)
        ).scalars().all()
        reason = f"ПК не появился в сети за {settings.waiting_task_ttl_days} дн., задача отменена."
        return sum(cancel_waiting_task(db, task, reason) for task in stale)
    finally:
        db.close()
