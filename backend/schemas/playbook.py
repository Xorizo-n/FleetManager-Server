import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class PlaybookRepoCreate(BaseModel):
    name: str
    git_url: str
    git_token: str | None = None
    credential_id: uuid.UUID | None = None
    branch: str = "main"


class PlaybookRepoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: str = "git"
    git_url: str
    credential_id: uuid.UUID | None
    branch: str
    created_at: datetime


class PlaybookFileOut(BaseModel):
    name: str
    path: str
    display_name: str | None = None


def _validate_cron(value: str) -> str:
    from croniter import croniter

    value = " ".join(value.split())
    if not croniter.is_valid(value):
        raise ValueError("Некорректное cron-выражение")
    return value


class PlaybookRunRequest(BaseModel):
    repo_id: uuid.UUID
    playbook_name: str
    host_ids: list[uuid.UUID] = []
    # Группы раскрываются вместе с подгруппами: корпус = все его аудитории.
    host_group_ids: list[uuid.UUID] = []
    host_group_id: uuid.UUID | None = None  # прежний клиент: одна группа
    extra_vars: dict = {}
    # Выключенные ПК получают отдельные задачи, которые запустятся при их появлении в сети
    defer_offline: bool = True


class PlaybookScheduleCreate(BaseModel):
    repo_id: uuid.UUID
    playbook_name: str
    host_group_id: uuid.UUID | None = None
    host_group_ids: list[uuid.UUID] = []
    host_ids: list[uuid.UUID] = []
    extra_vars: dict = {}
    cron_expression: str
    enabled: bool = True

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, value: str) -> str:
        return _validate_cron(value)


class PlaybookScheduleUpdate(BaseModel):
    playbook_name: str | None = None
    host_group_ids: list[uuid.UUID] | None = None
    host_ids: list[uuid.UUID] | None = None
    extra_vars: dict | None = None
    cron_expression: str | None = None
    enabled: bool | None = None

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, value: str | None) -> str | None:
        return None if value is None else _validate_cron(value)


class PlaybookScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repo_id: uuid.UUID
    playbook_name: str
    host_group_id: uuid.UUID | None
    host_group_ids: list[uuid.UUID] = []
    host_ids: list[uuid.UUID] = []
    extra_vars: dict = {}
    cron_expression: str
    enabled: bool
    created_at: datetime
    next_run_at: datetime | None = None

    @field_validator("host_group_ids", "host_ids", mode="before")
    @classmethod
    def none_as_empty_list(cls, value):
        return value or []

    @field_validator("extra_vars", mode="before")
    @classmethod
    def none_as_empty_dict(cls, value):
        return value or {}


class PlaybookContentOut(BaseModel):
    repo_id: uuid.UUID
    path: str
    content: str
    editable: bool
    modified_at: datetime | None = None


class PlaybookCheckRequest(BaseModel):
    content: str


class PlaybookSaveRequest(BaseModel):
    path: str
    content: str
    # Путь до сохранения: другой — переименование (расписания переезжают вместе с файлом); None — новый файл
    original_path: str | None = None
