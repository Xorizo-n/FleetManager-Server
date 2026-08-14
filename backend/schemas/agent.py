import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.host import HostOS, HostStatus


class AgentHardware(BaseModel):
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    operating_system: str | None = None
    processor: str | None = None
    total_memory_bytes: int | None = Field(default=None, ge=0)
    fingerprint: str | None = None


class AgentSoftware(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    version: str | None = Field(default=None, max_length=128)
    publisher: str | None = Field(default=None, max_length=255)
    source: str = Field(default="unknown", max_length=64)


class AgentRegisterRequest(BaseModel):
    enrollment_token: str = Field(min_length=16, max_length=512)
    machine_id: uuid.UUID
    hostname: str | None = Field(default=None, max_length=255)
    ip_address: str | None = Field(default=None, max_length=64)
    os: HostOS
    ssh_login: str | None = Field(default=None, max_length=255)
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    # Агенты до версии с поддержкой отчёта о версии поля не присылают — оно опционально.
    agent_version: str | None = Field(default=None, max_length=64)

    @field_validator("hostname", "ip_address", "ssh_login", "agent_version", mode="before")
    @classmethod
    def trim_address(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class AgentRegisterResponse(BaseModel):
    agent_id: uuid.UUID
    agent_token: str
    host_id: uuid.UUID
    hostname: str | None
    ip_address: str | None
    ssh_public_key: str | None
    ssh_login: str | None


class AgentUninstallRequest(BaseModel):
    machine_id: uuid.UUID


class AgentHeartbeatRequest(BaseModel):
    machine_id: uuid.UUID
    hostname: str | None = Field(default=None, max_length=255)
    ip_address: str | None = Field(default=None, max_length=64)
    ssh_login: str | None = Field(default=None, max_length=255)
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    os: HostOS
    status: HostStatus = HostStatus.online
    agent_version: str | None = Field(default=None, max_length=64)
    hardware: AgentHardware = Field(default_factory=AgentHardware)
    software: list[AgentSoftware] = Field(default_factory=list, max_length=10000)

    @field_validator("ssh_login", "agent_version", mode="before")
    @classmethod
    def trim_ssh_login(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class AgentAlertRequest(BaseModel):
    machine_id: uuid.UUID
    alert_type: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=4000)
    previous_fingerprint: str | None = Field(default=None, max_length=128)
    current_fingerprint: str | None = Field(default=None, max_length=128)


class AgentOfflineRequest(BaseModel):
    machine_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=512)


class AgentEnrollmentTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    expires_at: datetime | None = None


class AgentEnrollmentTokenResponse(BaseModel):
    id: uuid.UUID
    name: str
    expires_at: datetime | None
    is_active: bool
    raw_token: str


class AgentEnrollmentTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    expires_at: datetime | None
    is_active: bool
    created_at: datetime


class AgentAlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    host_id: uuid.UUID
    alert_type: str
    message: str
    previous_fingerprint: str | None
    current_fingerprint: str | None
    created_at: datetime


class AgentHostVersionOut(BaseModel):
    host_id: uuid.UUID
    hostname: str | None
    ip_address: str | None
    has_agent: bool
    agent_version: str | None
    version_status: str
    agent_version_checked_at: datetime | None
    last_seen_at: datetime | None
    status: HostStatus


class AgentVersionOverviewOut(BaseModel):
    available_version: str | None
    installer_present: bool
    total_agents: int
    up_to_date: int
    outdated: int
    unknown: int
    hosts: list[AgentHostVersionOut]


class AgentHostSelection(BaseModel):
    """Хосты для обслуживания агента; пустой список — все хосты с агентом."""

    host_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)


class AgentStatusOut(BaseModel):
    agent_id: uuid.UUID
    host_id: uuid.UUID
    hostname: str | None
    ip_address: str | None
    os: HostOS
    status: HostStatus
    last_seen_at: datetime | None
    last_shutdown_at: datetime | None
    hardware_fingerprint: str | None
    alerts: list[AgentAlertOut]
