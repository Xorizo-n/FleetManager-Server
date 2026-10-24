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
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    # От чьего имени выполнялось (services/run_as.py): {login, reason, as_user, fallback}
    run_as: dict | None = None
    # Запущена ожидающей задачей для появившихся ПК / следующий плейбук после этой задачи
    parent_id: uuid.UUID | None = None
    after_task_id: uuid.UUID | None = None
    # Ответ на запуск: задачи, созданные для выключенных ПК (ждут их появления в сети)
    waiting_task_ids: list[uuid.UUID] = []
    waiting_hosts: int = 0


class TaskRunDetailOut(TaskRunOut):
    log_output: str | None
    extra_vars: dict | None
