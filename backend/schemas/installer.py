from datetime import datetime

from pydantic import BaseModel


class InstallerFileOut(BaseModel):
    name: str
    size: int
    mtime: datetime
    # Лежит ли эта версия файла на точке раздачи; None — точка раздачи не настроена
    distributed: bool | None = None


class InstallerUploadResult(BaseModel):
    name: str
    size: int
    replaced: bool


class AgentInstallerSyncResult(BaseModel):
    updated: bool
    version: str | None = None
    reason: str | None = None


class DistributionStatus(BaseModel):
    enabled: bool
    url: str | None = None
    running: bool = False
    healthy: bool | None = None
    checked_at: datetime | None = None
    last_attempt: datetime | None = None
    last_success: datetime | None = None
    error: str | None = None
    files: int | None = None
    bytes: int | None = None
    pending: int | None = None
