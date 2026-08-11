import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class HostStatus(str, enum.Enum):
    online = "online"
    offline = "offline"
    unknown = "unknown"


class HostOS(str, enum.Enum):
    windows_10 = "windows_10"
    windows_11 = "windows_11"
    windows_server = "windows_server"


class HostGroup(Base):
    __tablename__ = "host_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    credential_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True)

    credential: Mapped["Credential"] = relationship(back_populates="host_groups")
    hosts: Mapped[list["Host"]] = relationship(back_populates="group")


class Host(Base):
    __tablename__ = "hosts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("host_groups.id", ondelete="SET NULL"), nullable=True)
    os: Mapped[HostOS] = mapped_column(Enum(HostOS), nullable=False)
    status: Mapped[HostStatus] = mapped_column(Enum(HostStatus), default=HostStatus.unknown, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    credential_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True)

    # Agent registration & auth
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True, nullable=True, index=True)
    agent_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    hardware_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_shutdown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_agent_managed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ssh_port: Mapped[int] = mapped_column(Integer, default=22, nullable=False)

    # Hardware inventory (populated by agent heartbeat)
    hw_manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hw_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hw_serial_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hw_os_caption: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hw_processor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    hw_total_memory_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    group: Mapped["HostGroup"] = relationship(back_populates="hosts")
    credential: Mapped["Credential"] = relationship(back_populates="hosts")
    software_items: Mapped[list["SoftwareItem"]] = relationship(back_populates="host", cascade="all, delete-orphan")


class HostStatusHistory(Base):
    __tablename__ = "host_status_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[HostStatus] = mapped_column(Enum(HostStatus), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
