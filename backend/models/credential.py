import enum
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func, Enum, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class CredentialType(str, enum.Enum):
    ssh_key = "ssh_key"
    password = "password"
    token = "token"


class Credential(Base):
    __tablename__ = "credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[CredentialType] = mapped_column(Enum(CredentialType), nullable=False)
    login: Mapped[str | None] = mapped_column(String(128), nullable=True)
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_agent_managed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    hosts: Mapped[list["Host"]] = relationship(back_populates="credential")
    host_groups: Mapped[list["HostGroup"]] = relationship(back_populates="credential")
