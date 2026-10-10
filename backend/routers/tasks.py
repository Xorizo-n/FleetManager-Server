import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import cast, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from database import SessionLocal, get_db
from dependencies import get_current_user
from models.task import TaskRun, TaskStatus, TaskType
from models.user import User
from schemas.task import TaskRunOut, TaskRunDetailOut
from services.task_visibility import can_view_task_type

router = APIRouter(prefix="/tasks", tags=["tasks"])

TERMINAL_STATUSES = (TaskStatus.success, TaskStatus.failed)


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
    query = select(TaskRun)
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
    return out


@router.get("/{task_id}/stream")
async def stream_task_log(task_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task_run = db.get(TaskRun, task_id)
    if task_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if not can_view_task_type(user.role, task_run.task_type):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient permissions")

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

                if task_run.status in TERMINAL_STATUSES:
                    yield {"event": "done", "data": task_run.status.value}
                    return
            finally:
                db.close()

            await asyncio.sleep(1)

    return EventSourceResponse(event_generator())
