import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
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
    return db.execute(query.order_by(TaskRun.created_at.desc()).limit(200)).scalars().all()


@router.get("/{task_id}", response_model=TaskRunDetailOut)
def get_task(task_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task_run = db.get(TaskRun, task_id)
    if task_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    if not can_view_task_type(user.role, task_run.task_type):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient permissions")
    return task_run


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
