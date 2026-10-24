"""Задачи для выключенных ПК: ждут, пока ПК появится в сети, и цепочки плейбуков.

При запуске плейбука, сканирования ПО или обслуживания агента ПК, которые
сейчас не в сети, не попадают в общую задачу: для них всех создаётся одна задача
в статусе waiting. Появившийся ПК (heartbeat или ответ на проверку по SSH — у ПК
без агента heartbeat нет) переходит из host_ids в ready_host_ids, а через
RELEASE_DELAY_SECONDS для всех накопившихся ПК запускается дочерняя задача
(parent_id): утром ПК включаются пачками, и одна задача на пачку вместо одной на
ПК. Когда ПК не осталось, ожидающая задача получает статус released; ПК, не
появившиеся за settings.waiting_task_ttl_days, отменяются вместе с ней.

Повторное назначение той же задачи (тот же тип и плейбук) на ПК забирает его из
прежних ожидающих задач: выполнится последнее назначение, а не оба.

Несколько плейбуков за раз — отдельные задачи, связанные after_task_id: каждая
следующая ждёт в статусе pending, пока не закончится предыдущая (успешно или
нет). У выключенных ПК так же связаны их ожидающие задачи, и пачка появившихся
ПК проходит плейбуки по порядку.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import cast, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB

from celery_app import celery_app
from config import settings
from database import SessionLocal
from models.host import Host, HostStatus
from models.task import TaskRun, TaskStatus, TaskType

# Задачи, которые имеет смысл выполнить позже. Диагностика нужна сейчас, а смена
# учётных данных проверяет вход сразу и применяется целиком.
DEFERRABLE_TYPES = frozenset({TaskType.playbook, TaskType.software_scan, TaskType.agent_version_scan, TaskType.agent_update})

# Сколько ждать после появления первого ПК, собирая остальных в ту же задачу. Заодно
# пауза перед запуском: агент стартует через пару минут после загрузки, sshd к этому
# времени уже работает, но пусть сеть окончательно поднимется.
RELEASE_DELAY_SECONDS = 60

# Поля, которые дочерняя задача и следующий плейбук цепочки берут у исходной
_COPIED_FIELDS = ("task_type", "repo_id", "playbook_name", "extra_vars", "created_by", "run_as_user_id")


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


def _log(task: TaskRun, line: str) -> None:
    task.log_output = f"{task.log_output}\n{line}" if task.log_output else line


def _host_names(db, host_ids) -> str:
    names = dict(db.execute(select(Host.id, Host.hostname).where(Host.id.in_([uuid.UUID(str(h)) for h in host_ids]))).all())
    return ", ".join(sorted(names.get(uuid.UUID(str(h))) or str(h) for h in host_ids))


def split_offline(db, host_ids: list[str]) -> tuple[list[str], list[str]]:
    """(в сети, не в сети). Хост, которого нет в реестре, идёт в сеть — задача сама сообщит об ошибке."""
    known = {str(host_id): status for host_id, status in db.execute(
        select(Host.id, Host.status).where(Host.id.in_([uuid.UUID(h) for h in host_ids]))
    ).all()}
    online = [h for h in host_ids if known.get(h, HostStatus.online) == HostStatus.online]
    offline = [h for h in host_ids if known.get(h, HostStatus.online) != HostStatus.online]
    return online, offline


def _same_assignment(db, task_type: TaskType, fields: dict) -> list[TaskRun]:
    """Ожидающие задачи того же типа и плейбука — их ПК забирает новое назначение."""
    query = select(TaskRun).where(TaskRun.status == TaskStatus.waiting, TaskRun.task_type == task_type)
    for key in ("repo_id", "playbook_name"):
        column = getattr(TaskRun, key)
        value = fields.get(key)
        query = query.where(column.is_(None) if value is None else column == value)
    return db.execute(query.order_by(TaskRun.created_at).with_for_update()).scalars().all()


def _supersede(db, task_type: TaskType, host_ids: list[str], fields: dict) -> None:
    """Забирает ПК нового назначения из прежних ожидающих задач; опустевшие отменяются."""
    wanted = set(host_ids)
    for task in _same_assignment(db, task_type, fields):
        taken = [h for h in task.host_ids if h in wanted]
        if not taken:
            continue
        task.host_ids = [h for h in task.host_ids if h not in wanted]
        _log(task, f"{_now():%d.%m.%Y %H:%M} UTC: назначена снова, ПК переходят в новую задачу: {_host_names(db, taken)}.")
        if not task.host_ids and not task.ready_host_ids:
            task.status = TaskStatus.cancelled
            task.finished_at = _now()
            _log(task, "Все ПК переназначены — задача отменена.")


def create_task_sequence(
    db,
    *,
    task_type: TaskType,
    host_ids: list[str],
    created_by: uuid.UUID | None,
    steps: list[dict],
    defer_offline: bool = True,
) -> tuple[list[TaskRun], list[TaskRun]]:
    """Задачи для ПК в сети и ожидающие задачи для выключенных, по одной на шаг (плейбук).

    Шаги выполняются по порядку: первая задача — queued, остальные — pending после
    предыдущей. Сохраняет, но не запускает: первую задачу для ПК в сети вызывающий
    отправляет в celery сам (enqueue).
    """
    if defer_offline and task_type in DEFERRABLE_TYPES:
        online, offline = split_offline(db, host_ids)
        for fields in steps:
            _supersede(db, task_type, host_ids, fields)
    else:
        online, offline = host_ids, []

    deadline = _now() + timedelta(days=settings.waiting_task_ttl_days)
    now_tasks: list[TaskRun] = []
    waiting: list[TaskRun] = []
    for fields in steps:
        if online:
            previous = now_tasks[-1] if now_tasks else None
            task = TaskRun(
                id=uuid.uuid4(),
                task_type=task_type,
                host_ids=online,
                status=TaskStatus.queued if previous is None else TaskStatus.pending,
                after_task_id=previous.id if previous else None,
                created_by=created_by,
                **fields,
            )
            db.add(task)
            now_tasks.append(task)
        if offline:
            previous = waiting[-1] if waiting else None
            task = TaskRun(
                id=uuid.uuid4(),
                task_type=task_type,
                host_ids=offline,
                ready_host_ids=[],
                status=TaskStatus.waiting,
                after_task_id=previous.id if previous else None,
                created_by=created_by,
                log_output=f"ПК не в сети: {len(offline)}. Для появившихся задача запустится сама, "
                           f"не появившиеся до {deadline:%d.%m.%Y %H:%M} UTC отменятся.",
                **fields,
            )
            db.add(task)
            waiting.append(task)

    db.commit()
    for task in now_tasks + waiting:
        db.refresh(task)
    return now_tasks, waiting


def create_task_runs(
    db,
    *,
    task_type: TaskType,
    host_ids: list[str],
    created_by: uuid.UUID | None,
    defer_offline: bool = True,
    **fields,
) -> tuple[TaskRun | None, TaskRun | None]:
    """Одна задача: (для ПК в сети, ожидающая для выключенных); любой может быть None."""
    now_tasks, waiting = create_task_sequence(
        db, task_type=task_type, host_ids=host_ids, created_by=created_by, steps=[fields], defer_offline=defer_offline,
    )
    return (now_tasks[0] if now_tasks else None), (waiting[0] if waiting else None)


def release_waiting_tasks(db, host_id: uuid.UUID, reason: str = "heartbeat") -> int:
    """ПК появился в сети: переходит в ready_host_ids своих ожидающих задач. Возвращает их число.

    В цепочке плейбуков ПК освобождает только первая задача, которая его ещё держит:
    следующие flush_released забирает вместе с ней. Строки блокируются (FOR UPDATE),
    поэтому heartbeat и проверка по SSH, пришедшие одновременно, ПК не задвоят.
    """
    host = str(host_id)
    tasks = db.execute(
        select(TaskRun).where(
            TaskRun.status == TaskStatus.waiting,
            or_(cast(TaskRun.host_ids, JSONB).contains([host]), cast(TaskRun.ready_host_ids, JSONB).contains([host])),
        ).with_for_update()
    ).scalars().all()
    if not tasks:
        db.commit()
        return 0

    holding = {task.id for task in tasks}
    released = []
    for task in tasks:
        if host not in task.host_ids or task.after_task_id in holding:
            continue
        task.host_ids = [h for h in task.host_ids if h != host]
        ready = list(task.ready_host_ids or [])
        task.ready_host_ids = ready + [host]
        if not ready:
            released.append(task)
    if released:
        line = f"{_now():%d.%m.%Y %H:%M} UTC: ПК появился в сети ({reason}): {_host_names(db, [host])}."
        for task in released:
            _log(task, line)
    db.commit()
    # Первый появившийся ПК назначает запуск, остальные до него просто добавляются
    for task in released:
        flush_released.apply_async(args=[str(task.id)], countdown=RELEASE_DELAY_SECONDS)
    return len(released)


def _finish_if_empty(task: TaskRun) -> None:
    if not task.host_ids and not task.ready_host_ids and task.status == TaskStatus.waiting:
        task.status = TaskStatus.released
        task.finished_at = _now()
        _log(task, "Все ПК появились в сети, задачи для них запущены.")


def _child(parent: TaskRun, host_ids: list[str], status: TaskStatus, after: TaskRun | None) -> TaskRun:
    return TaskRun(
        id=uuid.uuid4(),
        host_ids=host_ids,
        status=status,
        parent_id=parent.id,
        after_task_id=after.id if after else None,
        log_output=f"ПК появились в сети. Запущена ожидавшей задачей {parent.id}.",
        **{key: getattr(parent, key) for key in _COPIED_FIELDS},
    )


@celery_app.task(name="services.waiting_tasks.flush_released")
def flush_released(task_id: str) -> str | None:
    """Запускает ожидающую задачу для накопившихся появившихся ПК; цепочка за ней — по порядку."""
    db = SessionLocal()
    try:
        head = db.execute(select(TaskRun).where(TaskRun.id == uuid.UUID(task_id)).with_for_update()).scalar_one_or_none()
        if head is None or not head.ready_host_ids:
            db.commit()
            return None
        hosts = list(head.ready_host_ids)
        head.ready_host_ids = []
        if head.status != TaskStatus.waiting:
            # Отменили, пока ПК собирались
            db.commit()
            return None

        first = _child(head, hosts, TaskStatus.queued, None)
        db.add(first)
        _log(head, f"{_now():%d.%m.%Y %H:%M} UTC: запущена для {len(hosts)} ПК — задача {first.id}.")
        _finish_if_empty(head)

        previous, current = first, head
        while True:
            follower = db.execute(
                select(TaskRun).where(TaskRun.after_task_id == current.id, TaskRun.status == TaskStatus.waiting).with_for_update()
            ).scalars().first()
            if follower is None:
                break
            current = follower
            taken = [h for h in hosts if h in follower.host_ids]
            if not taken:
                continue  # эти ПК из следующего плейбука переназначили — смотрим дальше по цепочке
            follower.host_ids = [h for h in follower.host_ids if h not in taken]
            step = _child(follower, taken, TaskStatus.pending, previous)
            db.add(step)
            _log(follower, f"{_now():%d.%m.%Y %H:%M} UTC: {len(taken)} ПК появились в сети — задача {step.id} после предыдущего плейбука.")
            _finish_if_empty(follower)
            previous = step

        db.commit()
        enqueue(first)
        return str(first.id)
    finally:
        db.close()


def start_followers(db, task_id: uuid.UUID) -> int:
    """Задача закончилась: следующий плейбук цепочки уходит в очередь. Отменённый пропускается."""
    finished = db.get(TaskRun, task_id)
    started = 0
    for follower in db.execute(select(TaskRun).where(TaskRun.after_task_id == task_id)).scalars().all():
        if follower.status == TaskStatus.cancelled:
            started += start_followers(db, follower.id)
            continue
        claimed = db.execute(
            update(TaskRun).where(TaskRun.id == follower.id, TaskRun.status == TaskStatus.pending).values(status=TaskStatus.queued)
        ).rowcount
        db.commit()
        if not claimed:
            continue
        db.refresh(follower)
        result = finished.status.value if finished is not None else "—"
        _log(follower, f"{_now():%d.%m.%Y %H:%M} UTC: предыдущий плейбук завершён ({result}), задача запущена.")
        db.commit()
        enqueue(follower)
        started += 1
    return started


CANCELLABLE = (TaskStatus.waiting, TaskStatus.pending)


def cancel_waiting_task(db, task: TaskRun, reason: str) -> bool:
    """Отменяет ожидающую задачу или следующий плейбук цепочки. Запущенные не прерываются."""
    claimed = db.execute(
        update(TaskRun)
        .where(TaskRun.id == task.id, TaskRun.status.in_(CANCELLABLE))
        .values(status=TaskStatus.cancelled, finished_at=_now())
    ).rowcount
    db.commit()
    if claimed:
        db.refresh(task)
        _log(task, reason)
        db.commit()
    return bool(claimed)


@celery_app.task(name="services.waiting_tasks.expire_waiting_tasks")
def expire_waiting_tasks() -> int:
    """Отменяет задачи, чьи ПК не появились в сети за settings.waiting_task_ttl_days."""
    db = SessionLocal()
    try:
        cutoff = _now() - timedelta(days=settings.waiting_task_ttl_days)
        stale = db.execute(
            select(TaskRun).where(TaskRun.status == TaskStatus.waiting, TaskRun.created_at < cutoff)
        ).scalars().all()
        expired = 0
        for task in stale:
            names = _host_names(db, task.host_ids) if task.host_ids else ""
            reason = f"ПК не появились в сети за {settings.waiting_task_ttl_days} дн., задача отменена" + (f": {names}." if names else ".")
            expired += cancel_waiting_task(db, task, reason)
        return expired
    finally:
        db.close()
