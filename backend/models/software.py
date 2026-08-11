import enum
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class InstallMethod(str, enum.Enum):
    msi = "msi"
    chocolatey = "chocolatey"
    winget = "winget"
    other = "other"


class SoftwareStatus(str, enum.Enum):
    installed = "installed"
    removed = "removed"
    unknown = "unknown"


class ChangeType(str, enum.Enum):
    added = "added"
    removed = "removed"
    updated = "updated"


class SoftwareItem(Base):
    __tablename__ = "software_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    install_method: Mapped[InstallMethod] = mapped_column(Enum(InstallMethod), nullable=False)
    status: Mapped[SoftwareStatus] = mapped_column(Enum(SoftwareStatus), default=SoftwareStatus.installed, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    host: Mapped["Host"] = relationship(back_populates="software_items")


class SoftwareHistory(Base):
    __tablename__ = "software_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    old_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    new_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    change_type: Mapped[ChangeType] = mapped_column(Enum(ChangeType), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
