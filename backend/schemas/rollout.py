import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.rollout import RolloutItemStatus, RolloutStatus


def _clean(value):
    """Пустая строка — нет значения; многострочный текст (требования, заметки) не трогаем."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class RolloutItemIn(BaseModel):
    software: str = Field(min_length=1, max_length=255)
    rooms: str | None = Field(default=None, max_length=255)
    status: RolloutItemStatus = RolloutItemStatus.todo
    note: str | None = None
    task_run_id: uuid.UUID | None = None

    @field_validator("software", "rooms", "note", mode="before")
    @classmethod
    def strip_text(cls, value):
        return _clean(value)


class RolloutRequestCreate(BaseModel):
    partner: str | None = Field(default=None, max_length=255)
    course: str = Field(min_length=1, max_length=500)
    rooms: str | None = Field(default=None, max_length=255)
    schedule: str | None = Field(default=None, max_length=255)
    requirements: str | None = None
    status: RolloutStatus = RolloutStatus.new
    assignee_id: uuid.UUID | None = None
    due_date: date | None = None
    notes: str | None = None
    items: list[RolloutItemIn] = Field(default_factory=list, max_length=100)

    @field_validator("partner", "course", "rooms", "schedule", "requirements", "notes", mode="before")
    @classmethod
    def strip_text(cls, value):
        return _clean(value)


class RolloutRequestUpdate(RolloutRequestCreate):
    """Только переданные поля; items, если переданы, заменяют список позиций целиком."""

    course: str | None = Field(default=None, min_length=1, max_length=500)
    status: RolloutStatus | None = None
    items: list[RolloutItemIn] | None = Field(default=None, max_length=100)


class TaskProgress(BaseModel):
    """Итог связанного запуска: статус и сколько ПК в каждом состоянии."""

    status: str
    playbook_name: str | None = None
    created_at: datetime | None = None
    host_states: dict[str, int] = Field(default_factory=dict)


class RolloutItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    software: str
    rooms: str | None = None
    status: RolloutItemStatus
    note: str | None = None
    task_run_id: uuid.UUID | None = None
    task: TaskProgress | None = None


class RolloutRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    partner: str | None = None
    course: str
    rooms: str | None = None
    schedule: str | None = None
    requirements: str | None = None
    status: RolloutStatus
    assignee_id: uuid.UUID | None = None
    assignee_name: str | None = None
    due_date: date | None = None
    notes: str | None = None
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime
    items: list[RolloutItemOut] = Field(default_factory=list)


class RolloutAssignee(BaseModel):
    id: uuid.UUID
    name: str
