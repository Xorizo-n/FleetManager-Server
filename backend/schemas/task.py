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
    repo_id: uuid.UUID | None = None
    # Запуск на много ПК: состояние каждого ПК, выполняют дочерние задачи (services/waiting_tasks.py).
    # У выполняющей задачи host_states — её итог по ПК.
    grouped: bool | None = False
    host_states: dict | None = None
    # Выполняющая задача запуска / следующий плейбук цепочки после этой задачи
    parent_id: uuid.UUID | None = None
    after_task_id: uuid.UUID | None = None
    # Ответ на запуск: сколько ПК ждут появления в сети
    waiting_hosts: int = 0


class ChainStep(BaseModel):
    """Плейбук цепочки, запущенной одним запуском, — для навигации по ней."""
    id: uuid.UUID
    playbook_name: str | None
    status: TaskStatus


class TaskRunDetailOut(TaskRunOut):
    log_output: str | None
    extra_vars: dict | None
    # Выполняющие задачи запуска: сразу для ПК в сети и по одной на пачку появившихся
    runs: list[TaskRunOut] = []
    chain: list[ChainStep] = []
