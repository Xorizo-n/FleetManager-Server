import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models.host import HostStatus, HostOS
from services.host_target import normalize_host_address, resolve_host_target


class HostGroupCreate(BaseModel):
    name: str
    description: str | None = None
    credential_id: uuid.UUID | None = None


class HostGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    credential_id: uuid.UUID | None


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


class HostCreate(BaseModel):
    ip_address: str | None = None
    hostname: str | None = None
    group_id: uuid.UUID | None = None
    os: HostOS
    comment: str | None = None
    credential_id: uuid.UUID | None = None
    ssh_port: int | None = Field(default=None, ge=1, le=65535)

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
    ssh_port: int | None = Field(default=None, ge=1, le=65535)

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
    ssh_port: int
    created_at: datetime
    updated_at: datetime
    agent_id: uuid.UUID | None = None
    hardware_fingerprint: str | None = None
    last_seen_at: datetime | None = None
    last_shutdown_at: datetime | None = None


class CsvImportResult(BaseModel):
    created: int
    skipped: int
    errors: list[str]
