import uuid
from datetime import datetime

from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from config import settings


class WallpaperOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    original_name: str | None = None
    content_type: str
    sha256: str
    size_bytes: int
    width: int
    height: int
    created_at: datetime
    # Миниатюра JPEG в base64: <img> не передаёт токен, поэтому картинки идут вместе со списком
    thumbnail_base64: str = ""
    # Перцептивный хэш миниатюры (services.wallpapers.perceptual_hash)
    phash: str | None = None


class WallpaperRename(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class ObservedWallpaperOut(BaseModel):
    sha256: str
    path: str | None = None
    thumbnail_base64: str
    phash: str | None = None


class WallpaperAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    host_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    kind: str
    wallpaper_id: uuid.UUID
    updated_at: datetime


class WallpaperAssignRequest(BaseModel):
    """Назначить обои. desktop/lock_screen: id из каталога, "clear" — снять назначение
    (ПК вернётся к обоям группы или образа), None — этот вид не менять. apply_at — сменить
    в заданное время, иначе сразу."""

    host_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5000)
    group_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)
    desktop: str | None = Field(default=None, max_length=40)
    lock_screen: str | None = Field(default=None, max_length=40)
    apply_at: datetime | None = None
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("apply_at")
    @classmethod
    def _local_time(cls, value: datetime | None) -> datetime | None:
        # Время без пояса — местное, как у расписаний плейбуков
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo(settings.schedule_timezone))
        return value

    @field_validator("desktop", "lock_screen")
    @classmethod
    def _value(cls, value: str | None) -> str | None:
        if value is None or value == "clear":
            return value
        return str(uuid.UUID(value))


class WallpaperAssignResult(BaseModel):
    changed: int = 0
    schedule_id: uuid.UUID | None = None


class WallpaperScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    apply_at: datetime
    host_ids: list[str]
    group_ids: list[str]
    desktop: str | None = None
    lock_screen: str | None = None
    comment: str | None = None
    status: str
    result: str | None = None
    created_at: datetime
    applied_at: datetime | None = None
    created_by_name: str | None = None
