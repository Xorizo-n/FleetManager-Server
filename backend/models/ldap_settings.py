import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class LdapSettings(Base):
    """Настройки входа через домен, заданные в интерфейсе (одна строка, id = 1).

    Пока строки нет, действуют LDAP_* из .env (services/ldap_config.py). Пароль служебной
    записи хранится зашифрованным ключом CREDENTIAL_ENCRYPTION_KEY и наружу не отдаётся."""

    __tablename__ = "ldap_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    base_dn: Mapped[str] = mapped_column(String(512), nullable=False)
    bind_dn: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    bind_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_groups: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    operator_groups: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    viewer_groups: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
