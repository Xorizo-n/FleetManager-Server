import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class BackupSettings(Base):
    """Хранилище резервных копий вне ВМ (одна строка, id = 1): restic по SFTP (services/offsite_backup.py).

    Пароли вводятся в интерфейсе и хранятся зашифрованными CREDENTIAL_ENCRYPTION_KEY; наружу не
    отдаются. Пароль шифрования копий нужно хранить и вне сервера: без него копии не открыть."""

    __tablename__ = "backup_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sftp_host: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    sftp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    sftp_user: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    sftp_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    sftp_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    repo_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Ключ SSH хранилища, принятый при первой проверке: дальше вход только к нему
    host_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Хранилище restic создано — пароль шифрования копий больше не меняется простой правкой
    initialized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class BackupRun(Base):
    """Запуск копирования или проверки: db (БД + конфигурация), share (/mnt/soft-share), check (проверка восстановления)."""

    __tablename__ = "backup_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    bytes_added: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
