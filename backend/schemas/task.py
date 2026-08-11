import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from models.task import TaskType, TaskStatus


class TaskRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_type: TaskType
    playbook_name: str | None
    host_ids: list
    status: TaskStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class TaskRunDetailOut(TaskRunOut):
    log_output: str | None
    extra_vars: dict | None
