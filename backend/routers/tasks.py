import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import cast, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from database import SessionLocal, get_db
from dependencies import get_current_user, oauth2_scheme, require_roles
from services.security import decode_token
from models.task import TaskRun, TaskStatus, TaskType
from models.user import User, UserRole
from schemas.task import ChainStep, TaskRunOut, TaskRunDetailOut
from services.task_visibility import can_view_task_type
from services.waiting_tasks import cancel_waiting_task

router = APIRouter(prefix="/tasks", tags=["tasks"])

TERMINAL_STATUSES = (TaskStatus.success, TaskStatus.failed, TaskStatus.cancelled, TaskStatus.released)
# Задача ничего не выполняет сейчас: поток журнала не держим
IDLE_STATUSES = (TaskStatus.waiting, TaskStatus.pending)


@router.get("", response_model=list[TaskRunOut])
def list_tasks(
    task_type: TaskType | None = None,
    status_filter: TaskStatus | None = None,
    host_id: uuid.UUID | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Выполняющие задачи запусков в списке не показываются — только сам запуск
    query = select(TaskRun).where(TaskRun.parent_id.is_(None))
    if not can_view_task_type(user.role, TaskType.host_diagnostic):
        query = query.where(TaskRun.task_type != TaskType.host_diagnostic)
    if task_type:
        query = query.where(TaskRun.task_type == task_type)
    if status_filter:
        query = query.where(TaskRun.status == status_filter)
    if host_id:
        query = query.where(cast(TaskRun.host_ids, JSONB).contains([str(host_id)]))
    tasks = db.execute(query.order_by(TaskRun.created_at.desc()).offset(offset).limit(limit)).scalars().all()
    return with_author_names(db, tasks)


def with_author_names(db: Session, tasks: list[TaskRun]) -> list[TaskRunOut]:
    """Кто запустил задачу; у задач по расписанию автора нет."""
    author_ids = {task.created_by for task in tasks if task.created_by}
    names = dict(db.execute(select(User.id, User.username).where(User.id.in_(author_ids))).all()) if author_ids else {}
    result = []
    for task in tasks:
        out = TaskRunOut.model_validate(task)
        out.created_by_name = names.get(task.created_by)
        result.append(out)
    return result


@router.get("/{task_id}", response_model=TaskRunDetailOut)
def get_task(task_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task_run = db.get(TaskRun, task_id)
    if task_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    if not can_view_task_type(user.role, task_run.task_type):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient permissions")
    out = TaskRunDetailOut.model_validate(task_run)
    out.created_by_name = with_author_names(db, [task_run])[0].created_by_name
    if task_run.grouped:
        # Без отменённых до старта (лишние ожидающие задачи старого формата, плейбук, снятый с цепочки)
        runs = db.execute(
            select(TaskRun)
            .where(TaskRun.parent_id == task_run.id, (TaskRun.started_at.isnot(None)) | (TaskRun.status != TaskStatus.cancelled))
            .order_by(TaskRun.created_at)
        ).scalars().all()
        out.runs = [TaskRunOut.model_validate(run) for run in runs]
        out.chain = [ChainStep.model_validate(step, from_attributes=True) for step in _chain(db, task_run)]
    return out


def _chain(db: Session, task_run: TaskRun) -> list[TaskRun]:
    """Запуски одной цепочки плейбуков по порядку; у одиночного запуска — пусто."""
    first = task_run
    while first.after_task_id is not None:
        previous = db.get(TaskRun, first.after_task_id)
        if previous is None:
            break
        first = previous
    steps = [first]
    while len(steps) < 50:
        following = db.execute(
            select(TaskRun).where(TaskRun.after_task_id == steps[-1].id, TaskRun.grouped.is_(True))
        ).scalars().first()
        if following is None:
            break
        steps.append(following)
    return steps if len(steps) > 1 else []


@router.post("/{task_id}/cancel", response_model=TaskRunOut)
def cancel_task(
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin, UserRole.operator)),
):
    """Отменяет то, что ещё не началось: ПК, ждущие появления в сети или предыдущий плейбук. Запущенное не прерывается."""
    task_run = db.get(TaskRun, task_id)
    if task_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    if not cancel_waiting_task(db, task_run, f"Отменена пользователем {user.username}."):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Отменять нечего: ни один ПК не ждёт появления в сети или предыдущий плейбук")
    return with_author_names(db, [task_run])[0]


@router.get("/{task_id}/stream")
async def stream_task_log(task_id: uuid.UUID, token: str = Depends(oauth2_scheme)):
    # ВАЖНО: не используем Depends(get_db)/get_current_user — для SSE-ответа FastAPI
    # держит yield-зависимости (и их соединение с БД, с открытой транзакцией) весь
    # стрим, что копит «idle in transaction» и исчерпывает пул. Авторизацию и начальную
    # проверку делаем короткоживущей сессией и закрываем её ДО старта стрима.
    db = SessionLocal()
    try:
        try:
            payload = decode_token(token)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется access-токен")
        user = db.get(User, uuid.UUID(payload["sub"]))
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден или деактивирован")

        task_run = db.get(TaskRun, task_id)
        if task_run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
        if not can_view_task_type(user.role, task_run.task_type):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient permissions")
    finally:
        db.close()

    async def event_generator():
        last_len = 0
        while True:
            db = SessionLocal()
            try:
                task_run = db.get(TaskRun, task_id)
                if task_run is None:
                    yield {"event": "error", "data": "task not found"}
                    return

                log = task_run.log_output or ""
                if len(log) > last_len:
                    yield {"event": "log", "data": log[last_len:]}
                    last_len = len(log)

                # Ожидающая задача может ждать ПК днями — поток не держим
                if task_run.status in TERMINAL_STATUSES or task_run.status in IDLE_STATUSES or task_run.grouped:
                    yield {"event": "done", "data": task_run.status.value}
                    return
            finally:
                db.close()

            await asyncio.sleep(1)

    return EventSourceResponse(event_generator())
