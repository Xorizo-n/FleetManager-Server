import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

# Вид обоев: рабочий стол или экран блокировки
DESKTOP = "desktop"
LOCK_SCREEN = "lock_screen"
WALLPAPER_KINDS = (DESKTOP, LOCK_SCREEN)


class Wallpaper(Base):
    """Изображение каталога обоев. Файл лежит в settings.wallpaper_dir под именем <sha256>.<расширение>."""

    __tablename__ = "wallpapers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    original_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_name: Mapped[str] = mapped_column(String(80), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    # Миниатюра JPEG 320 px — для каталога и карточек ПК
    thumbnail: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WallpaperAssignment(Base):
    """Назначение обоев ПК или группе. У ПК действует своё назначение, иначе — ближайшей
    группы вверх по дереву (аудитория → этаж → корпус); нет нигде — обоями сервер не управляет."""

    __tablename__ = "wallpaper_assignments"
    __table_args__ = (
        CheckConstraint("(host_id IS NULL) <> (group_id IS NULL)", name="ck_wallpaper_assignment_target"),
        UniqueConstraint("host_id", "kind", name="uq_wallpaper_assignment_host"),
        UniqueConstraint("group_id", "kind", name="uq_wallpaper_assignment_group"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"), nullable=True, index=True)
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("host_groups.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    wallpaper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("wallpapers.id", ondelete="RESTRICT"), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    wallpaper: Mapped["Wallpaper"] = relationship()


class WallpaperSchedule(Base):
    """Смена обоев в заданное время: в apply_at назначения применяются так же, как «сейчас»."""

    __tablename__ = "wallpaper_schedules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    apply_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    host_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    group_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Для каждого вида: id обоев, "clear" — снять назначение, None — не менять
    desktop: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lock_screen: Mapped[str | None] = mapped_column(String(40), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # pending / applied / cancelled / failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ObservedWallpaper(Base):
    """Изображение не из каталога, которое стоит на ПК (например, обои из образа): миниатюру
    присылает агент по запросу сервера, чтобы и такие обои было видно."""

    __tablename__ = "observed_wallpapers"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
