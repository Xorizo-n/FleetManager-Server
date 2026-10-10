import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from models.host import HostStatus, HostOS
from schemas.task import TaskRunOut
from services.host_target import normalize_host_address, resolve_host_target


class HostGroupCreate(BaseModel):
    name: str
    description: str | None = None
    credential_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None


class HostGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    credential_id: uuid.UUID | None
    parent_id: uuid.UUID | None = None
    is_auto: bool = False


class HostGroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    # null снимает учётку: тогда действует учётка родительской группы
    credential_id: uuid.UUID | None = None

    @field_validator("name", "description", mode="before")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class AccessChangeRequest(BaseModel):
    """Смена учётки SSH с проверкой входа (services/access_change.py)."""

    action: Literal["set_host_credential", "set_group_credential", "move_to_group"]
    host_ids: list[uuid.UUID] = []
    group_id: uuid.UUID | None = None
    group_name: str | None = None
    # null: «как у группы» для хоста, «наследовать от родителя» для группы
    credential_id: uuid.UUID | None = None

    @field_validator("group_name", mode="before")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        return (value.strip() or None) if isinstance(value, str) else value

    @model_validator(mode="after")
    def check_target(self):
        if self.action in ("set_host_credential", "move_to_group") and not self.host_ids:
            raise ValueError("Необходимо выбрать хотя бы один хост")
        if self.action == "set_group_credential" and self.group_id is None:
            raise ValueError("Не указана группа")
        if self.action == "move_to_group" and self.group_id and self.group_name:
            raise ValueError("Укажите существующую группу или имя новой, не оба")
        return self


class AccessChangeResult(BaseModel):
    # Задача проверки входа; None — учётка ни у кого не менялась, изменение уже применено
    task: TaskRunOut | None
    applied: int
    to_check: int
    skipped: int


class HostBulkDeleteRequest(BaseModel):
    host_ids: list[uuid.UUID]

    @field_validator("host_ids")
    @classmethod
    def require_hosts(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if not value:
            raise ValueError("Необходимо выбрать хотя бы один хост")
        return value


class HostGroupAssignRequest(BaseModel):
    host_ids: list[uuid.UUID]
    group_id: uuid.UUID | None = None
    group_name: str | None = None

    @field_validator("group_name", mode="before")
    @classmethod
    def normalize_group_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def require_destination(self):
        if not self.host_ids:
            raise ValueError("Необходимо выбрать хотя бы один хост")
        if bool(self.group_id) == bool(self.group_name):
            raise ValueError("Укажите существующую группу или имя новой группы")
        return self


class HostGroupUnassignRequest(BaseModel):
    host_ids: list[uuid.UUID]

    @field_validator("host_ids")
    @classmethod
    def require_hosts(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if not value:
            raise ValueError("Необходимо выбрать хотя бы один хост")
        return value


class HostCreate(BaseModel):
    ip_address: str | None = None
    hostname: str | None = None
    group_id: uuid.UUID | None = None
    os: HostOS
    comment: str | None = None
    credential_id: uuid.UUID | None = None

    @field_validator("ip_address", "hostname", mode="before")
    @classmethod
    def normalize_address(cls, value: str | None) -> str | None:
        return normalize_host_address(value)

    @model_validator(mode="after")
    def require_target(self):
        resolve_host_target(self.hostname, self.ip_address)
        return self


class HostUpdate(BaseModel):
    ip_address: str | None = None
    hostname: str | None = None
    group_id: uuid.UUID | None = None
    os: HostOS | None = None
    status: HostStatus | None = None
    comment: str | None = None
    credential_id: uuid.UUID | None = None

    @field_validator("ip_address", "hostname", mode="before")
    @classmethod
    def normalize_address(cls, value: str | None) -> str | None:
        return normalize_host_address(value)


class HostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ip_address: str | None
    hostname: str | None
    group_id: uuid.UUID | None
    os: HostOS
    status: HostStatus
    last_checked_at: datetime | None
    comment: str | None
    credential_id: uuid.UUID | None
    has_agent: bool = False
    agent_version: str | None = None
    agent_version_checked_at: datetime | None = None
    last_seen_at: datetime | None = None
    # Железо из heartbeat агента: реестр хостов показывает его колонками
    hw_manufacturer: str | None = None
    hw_model: str | None = None
    hw_serial_number: str | None = None
    hw_os_caption: str | None = None
    hw_processor: str | None = None
    hw_total_memory_bytes: int | None = None
    created_at: datetime
    updated_at: datetime


class CsvImportResult(BaseModel):
    created: int
    skipped: int
    errors: list[str]
