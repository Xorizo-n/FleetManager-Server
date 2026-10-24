"""Запуск на много ПК — одна задача: состояние каждого ПК, ожидание выключенных, цепочки плейбуков.

Запуск плейбука, сканирования ПО или обслуживания агента — это одна задача-запуск
(grouped=True, в списке задач видна только она). Сама она не выполняется: в
host_states у неё состояние каждого ПК — waiting (не в сети), ready (появился,
ждёт пачку), pending (ждёт предыдущий плейбук), queued, running, success,
failed, cancelled. Выполняют её дочерние задачи (parent_id): одна сразу для ПК в
сети и по одной на каждую пачку появившихся ПК. Появившийся ПК (heartbeat или
ответ на проверку по SSH — у ПК без агента heartbeat нет) становится ready, и
через RELEASE_DELAY_SECONDS для всех накопившихся ПК запускается дочерняя задача:
утром ПК включаются пачками. ПК, не появившиеся за settings.waiting_task_ttl_days,
отменяются. Итог дочерней задачи по каждому ПК (её host_states, а если их нет —
её статус) переносится в запуск; статус запуска — сводка по ПК (_group_status).

Повторное назначение той же задачи (тот же тип и плейбук) на ПК отменяет его в
прежних запусках, где он ещё ждёт: выполнится последнее назначение, а не оба.

Несколько плейбуков за раз — отдельные запуски, связанные after_task_id; их
дочерние задачи тоже: следующая ждёт в статусе pending, пока не закончится
предыдущая (успешно или нет). Пачка появившихся ПК проходит плейбуки по порядку.

Начало и конец дочерней задачи отслеживают сигналы celery (task_prerun/postrun),
поэтому исполнители (ansible_runner, agent_update, software_scanner) о запусках
не знают — им достаточно заполнить свои host_states.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from celery.signals import task_postrun, task_prerun
from sqlalchemy import cast, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm.attributes import flag_modified

from celery_app import celery_app
from config import settings
from database import SessionLocal
from models.host import Host, HostStatus
from models.task import TaskRun, TaskStatus, TaskType

logger = logging.getLogger(__name__)

# Задачи, которые имеет смысл выполнить позже. Диагностика нужна сейчас, а смена
# учётных данных проверяет вход сразу и применяется целиком.
DEFERRABLE_TYPES = frozenset({TaskType.playbook, TaskType.software_scan, TaskType.agent_version_scan, TaskType.agent_update})

# Сколько ждать после появления первого ПК, собирая остальных в ту же пачку. Заодно
# пауза перед запуском: агент стартует через пару минут после загрузки, sshd к этому
# времени уже работает, но пусть сеть окончательно поднимется.
RELEASE_DELAY_SECONDS = 60

# Состояния ПК в запуске
WAITING, READY, PENDING, QUEUED, RUNNING = "waiting", "ready", "pending", "queued", "running"
SUCCESS, FAILED, CANCELLED = "success", "failed", "cancelled"
OPEN_STATES = frozenset({WAITING, READY, PENDING, QUEUED, RUNNING})

# Поля, которые дочерняя задача берёт у запуска
_COPIED_FIELDS = ("task_type", "repo_id", "playbook_name", "extra_vars", "created_by", "run_as_user_id")

# Celery-задачи, выполняющие дочерние задачи запусков
_EXECUTORS = {
    TaskType.playbook: "services.ansible_runner.run_playbook_task",
    TaskType.software_scan: "services.software_scanner.scan_software_task",
    TaskType.agent_version_scan: "services.agent_update.run_agent_version_scan",
    TaskType.agent_update: "services.agent_update.run_agent_update",
}


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


def _stamp() -> str:
    return f"{_now():%d.%m.%Y %H:%M} UTC"


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


def _group_status(states: dict) -> TaskStatus:
    """Сводный статус запуска по состояниям его ПК: сначала то, что ещё идёт."""
    values = set(states.values())
    if RUNNING in values:
        return TaskStatus.running
    if values & {QUEUED, READY}:
        return TaskStatus.queued
    if PENDING in values:
        return TaskStatus.pending
    if WAITING in values:
        return TaskStatus.waiting
    if FAILED in values:
        return TaskStatus.failed
    if SUCCESS in values:
        return TaskStatus.success
    return TaskStatus.cancelled


def _set_states(group: TaskRun, changes: dict) -> None:
    """Меняет состояния ПК запуска и пересчитывает его статус."""
    if not changes:
        return
    group.host_states = {**(group.host_states or {}), **changes}
    if hasattr(group, "_sa_instance_state"):
        flag_modified(group, "host_states")
    group.status = _group_status(group.host_states)
    if group.started_at is None and RUNNING in group.host_states.values():
        group.started_at = _now()
    if set(group.host_states.values()) & OPEN_STATES:
        group.finished_at = None
    elif group.finished_at is None:
        group.finished_at = _now()


def _hosts_in(group: TaskRun, *states: str) -> list[str]:
    return [h for h, s in (group.host_states or {}).items() if s in states]


def waiting_count(group: TaskRun) -> int:
    """Сколько ПК запуска ждут появления в сети."""
    return len(_hosts_in(group, WAITING))


def _open_groups(db, task_type: TaskType, fields: dict) -> list[TaskRun]:
    """Незавершённые запуски того же типа и плейбука — их ожидающие ПК забирает новое назначение."""
    query = select(TaskRun).where(TaskRun.grouped.is_(True), TaskRun.finished_at.is_(None), TaskRun.task_type == task_type)
    for key in ("repo_id", "playbook_name"):
        column = getattr(TaskRun, key)
        value = fields.get(key)
        query = query.where(column.is_(None) if value is None else column == value)
    return db.execute(query.order_by(TaskRun.created_at).with_for_update()).scalars().all()


def _supersede(db, task_type: TaskType, host_ids: list[str], fields: dict) -> None:
    """Отменяет ПК нового назначения там, где они ещё ждут появления в сети."""
    wanted = set(host_ids)
    for group in _open_groups(db, task_type, fields):
        taken = [h for h in _hosts_in(group, WAITING) if h in wanted]
        if not taken:
            continue
        _set_states(group, {h: CANCELLED for h in taken})
        _log(group, f"{_stamp()}: назначена снова — здесь отменены ПК ({len(taken)}): {_host_names(db, taken)}.")


def create_task_sequence(
    db,
    *,
    task_type: TaskType,
    host_ids: list[str],
    created_by: uuid.UUID | None,
    steps: list[dict],
    defer_offline: bool = True,
) -> tuple[list[TaskRun], TaskRun | None]:
    """Запуски, по одному на шаг (плейбук), и первая дочерняя задача для ПК в сети.

    Сохраняет, но не запускает: дочернюю задачу вызывающий отправляет в celery сам (enqueue).
    Дочерние задачи следующих шагов ждут в pending и стартуют после предыдущей.
    """
    if defer_offline and task_type in DEFERRABLE_TYPES:
        online, offline = split_offline(db, host_ids)
        for fields in steps:
            _supersede(db, task_type, host_ids, fields)
    else:
        online, offline = host_ids, []

    deadline = _now() + timedelta(days=settings.waiting_task_ttl_days)
    groups: list[TaskRun] = []
    executions: list[TaskRun] = []
    for index, fields in enumerate(steps):
        first = index == 0
        states = {h: (QUEUED if first else PENDING) for h in online} | {h: WAITING for h in offline}
        group = TaskRun(
            id=uuid.uuid4(),
            task_type=task_type,
            grouped=True,
            host_ids=list(host_ids),
            host_states=states,
            status=_group_status(states),
            after_task_id=groups[-1].id if groups else None,
            created_by=created_by,
            **fields,
        )
        if offline:
            _log(group, f"Не в сети: {len(offline)} ПК. Для каждого задача запустится, когда он появится; "
                        f"не появившиеся до {deadline:%d.%m.%Y %H:%M} UTC отменятся.")
        db.add(group)
        groups.append(group)
        if online:
            execution = TaskRun(
                id=uuid.uuid4(),
                host_ids=list(online),
                status=TaskStatus.queued if first else TaskStatus.pending,
                parent_id=group.id,
                after_task_id=executions[-1].id if executions else None,
                **{key: getattr(group, key) for key in _COPIED_FIELDS},
            )
            db.add(execution)
            executions.append(execution)

    db.commit()
    for task in groups + executions:
        db.refresh(task)
    return groups, (executions[0] if executions else None)


def create_task_runs(
    db,
    *,
    task_type: TaskType,
    host_ids: list[str],
    created_by: uuid.UUID | None,
    defer_offline: bool = True,
    **fields,
) -> tuple[TaskRun, TaskRun | None]:
    """Один запуск: (запуск, дочерняя задача для ПК в сети или None)."""
    groups, execution = create_task_sequence(
        db, task_type=task_type, host_ids=host_ids, created_by=created_by, steps=[fields], defer_offline=defer_offline,
    )
    return groups[0], execution


def _earlier_in_chain(db, group: TaskRun) -> set[uuid.UUID]:
    """Предыдущие плейбуки цепочки — вплоть до первого, даже если в каком-то ПК отменён."""
    earlier: set[uuid.UUID] = set()
    previous_id = group.after_task_id
    while previous_id is not None and previous_id not in earlier and len(earlier) < 50:
        earlier.add(previous_id)
        previous = db.get(TaskRun, previous_id)
        previous_id = previous.after_task_id if previous is not None else None
    return earlier


def release_waiting_tasks(db, host_id: uuid.UUID, reason: str = "heartbeat") -> int:
    """ПК появился в сети: в запусках, где он ждёт, становится ready. Возвращает число запусков.

    В цепочке плейбуков ПК освобождает только первый запуск, который его ещё держит:
    следующие flush_released забирает вместе с ним. Строки блокируются (FOR UPDATE),
    поэтому heartbeat и проверка по SSH, пришедшие одновременно, ПК не задвоят.
    """
    host = str(host_id)
    state = cast(TaskRun.host_states, JSONB)[host].astext
    groups = db.execute(
        select(TaskRun)
        .where(TaskRun.grouped.is_(True), TaskRun.finished_at.is_(None), state.in_([WAITING, READY]))
        .with_for_update()
    ).scalars().all()
    if not groups:
        db.commit()
        return 0

    holding = {group.id for group in groups}
    released = []
    for group in groups:
        if group.host_states.get(host) != WAITING or _earlier_in_chain(db, group) & holding:
            continue
        first_in_batch = not _hosts_in(group, READY)
        _set_states(group, {host: READY})
        if first_in_batch:
            released.append(group)
            _log(group, f"{_stamp()}: ПК появились в сети ({reason}), через минуту запуск для всех появившихся.")
    db.commit()
    # Первый появившийся ПК назначает запуск, остальные до него просто добавляются
    for group in released:
        flush_released.apply_async(args=[str(group.id)], countdown=RELEASE_DELAY_SECONDS)
    return len(released)


def _execution(group: TaskRun, host_ids: list[str], status: TaskStatus, after: TaskRun | None) -> TaskRun:
    return TaskRun(
        id=uuid.uuid4(),
        host_ids=host_ids,
        status=status,
        parent_id=group.id,
        after_task_id=after.id if after else None,
        **{key: getattr(group, key) for key in _COPIED_FIELDS},
    )


@celery_app.task(name="services.waiting_tasks.flush_released")
def flush_released(task_id: str) -> str | None:
    """Запускает дочернюю задачу для накопившихся появившихся ПК; цепочка за ней — по порядку."""
    db = SessionLocal()
    try:
        head = db.execute(select(TaskRun).where(TaskRun.id == uuid.UUID(task_id)).with_for_update()).scalar_one_or_none()
        hosts = _hosts_in(head, READY) if head is not None else []
        if not hosts:
            db.commit()
            return None

        first = _execution(head, hosts, TaskStatus.queued, None)
        db.add(first)
        _set_states(head, {h: QUEUED for h in hosts})
        _log(head, f"{_stamp()}: запуск для появившихся ПК ({len(hosts)}): {_host_names(db, hosts)}.")

        previous, current = first, head
        while True:
            follower = db.execute(
                select(TaskRun).where(TaskRun.after_task_id == current.id, TaskRun.grouped.is_(True)).with_for_update()
            ).scalars().first()
            if follower is None:
                break
            current = follower
            taken = [h for h in hosts if follower.host_states.get(h) == WAITING]
            if not taken:
                continue  # эти ПК в следующем плейбуке отменили — смотрим дальше по цепочке
            step = _execution(follower, taken, TaskStatus.pending, previous)
            db.add(step)
            _set_states(follower, {h: PENDING for h in taken})
            _log(follower, f"{_stamp()}: ПК появились в сети ({len(taken)}) — запуск после предыдущего плейбука.")
            previous = step

        db.commit()
        enqueue(first)
        return str(first.id)
    finally:
        db.close()


def _parent_for_update(db, execution: TaskRun) -> TaskRun | None:
    if execution.parent_id is None:
        return None
    return db.execute(select(TaskRun).where(TaskRun.id == execution.parent_id).with_for_update()).scalar_one_or_none()


def execution_started(db, task_id: uuid.UUID) -> None:
    """Дочерняя задача началась: её ПК в запуске — running."""
    execution = db.get(TaskRun, task_id)
    group = _parent_for_update(db, execution) if execution is not None else None
    if group is not None:
        _set_states(group, {h: RUNNING for h in execution.host_ids if group.host_states.get(h) in (QUEUED, PENDING)})
    db.commit()


def host_results(execution: TaskRun) -> dict:
    """Итог по каждому ПК: что записал исполнитель, иначе статус задачи целиком."""
    own = execution.host_states or {}
    fallback = SUCCESS if execution.status == TaskStatus.success else CANCELLED if execution.status == TaskStatus.cancelled else FAILED
    return {h: own.get(h) if own.get(h) in (SUCCESS, FAILED, CANCELLED) else fallback for h in execution.host_ids}


def execution_finished(db, task_id: uuid.UUID) -> None:
    """Дочерняя задача закончилась: итог по ПК — в запуск, следующий плейбук цепочки — в очередь."""
    execution = db.get(TaskRun, task_id)
    if execution is None:
        return
    group = _parent_for_update(db, execution)
    if group is not None:
        results = host_results(execution)
        _set_states(group, {h: s for h, s in results.items() if group.host_states.get(h) in (QUEUED, RUNNING, PENDING)})
    db.commit()
    start_followers(db, task_id)


def start_followers(db, task_id: uuid.UUID) -> int:
    """Задача закончилась: следующий плейбук цепочки уходит в очередь. Отменённый пропускается."""
    finished = db.get(TaskRun, task_id)
    started = 0
    for follower in db.execute(select(TaskRun).where(TaskRun.after_task_id == task_id, TaskRun.grouped.is_(False))).scalars().all():
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
        _log(follower, f"{_stamp()}: предыдущий плейбук завершён ({result}), задача запущена.")
        group = _parent_for_update(db, follower)
        if group is not None:
            _set_states(group, {h: QUEUED for h in follower.host_ids if group.host_states.get(h) == PENDING})
        db.commit()
        enqueue(follower)
        started += 1
    return started


def cancel_waiting_task(db, task: TaskRun, reason: str) -> bool:
    """Отменяет то, что ещё не началось: у запуска — ждущие ПК и плейбуки в очереди цепочки,
    у отдельной задачи — ожидание. Выполняющиеся задачи не прерываются."""
    if task.grouped:
        group = db.execute(select(TaskRun).where(TaskRun.id == task.id).with_for_update()).scalar_one()
        hosts = _hosts_in(group, WAITING, READY, PENDING)
        db.execute(
            update(TaskRun)
            .where(TaskRun.parent_id == group.id, TaskRun.status == TaskStatus.pending)
            .values(status=TaskStatus.cancelled, finished_at=_now())
        )
        if hosts:
            _set_states(group, {h: CANCELLED for h in hosts})
            _log(group, f"{reason} Отменено ПК: {len(hosts)}.")
        db.commit()
        db.refresh(task)
        return bool(hosts)

    claimed = db.execute(
        update(TaskRun)
        .where(TaskRun.id == task.id, TaskRun.status.in_((TaskStatus.waiting, TaskStatus.pending)))
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
    """Отменяет ПК, не появившиеся в сети за settings.waiting_task_ttl_days. Возвращает число запусков."""
    db = SessionLocal()
    try:
        cutoff = _now() - timedelta(days=settings.waiting_task_ttl_days)
        stale = db.execute(
            select(TaskRun)
            .where(TaskRun.grouped.is_(True), TaskRun.finished_at.is_(None), TaskRun.created_at < cutoff)
            .with_for_update()
        ).scalars().all()
        expired = 0
        for group in stale:
            hosts = _hosts_in(group, WAITING)
            if not hosts:
                continue
            _set_states(group, {h: CANCELLED for h in hosts})
            _log(group, f"ПК не появились в сети за {settings.waiting_task_ttl_days} дн., отменены ({len(hosts)}): {_host_names(db, hosts)}.")
            expired += 1
        db.commit()
        return expired
    finally:
        db.close()


def _execution_id(sender, args, kwargs) -> uuid.UUID | None:
    if getattr(sender, "name", None) not in _EXECUTORS.values():
        return None
    raw = (args or [None])[0] or (kwargs or {}).get("task_run_id")
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


@task_prerun.connect
def _on_execution_start(sender=None, args=None, kwargs=None, **_):
    task_id = _execution_id(sender, args, kwargs)
    if task_id is None:
        return
    db = SessionLocal()
    try:
        execution_started(db, task_id)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("Failed to mark run %s started", task_id)
    finally:
        db.close()


@task_postrun.connect
def _on_execution_finish(sender=None, args=None, kwargs=None, **_):
    task_id = _execution_id(sender, args, kwargs)
    if task_id is None:
        return
    db = SessionLocal()
    try:
        execution_finished(db, task_id)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("Failed to record results of run %s", task_id)
    finally:
        db.close()
