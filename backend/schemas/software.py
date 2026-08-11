import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from models.software import InstallMethod, SoftwareStatus, ChangeType


class SoftwareItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    host_id: uuid.UUID
    name: str
    version: str | None
    install_method: InstallMethod
    status: SoftwareStatus
    detected_at: datetime


class SoftwareHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    host_id: uuid.UUID
    name: str
    old_version: str | None
    new_version: str | None
    change_type: ChangeType
    changed_at: datetime


class SoftwareSummaryItem(BaseModel):
    name: str
    version: str | None
    host_count: int


class ScanTriggerRequest(BaseModel):
    host_ids: list[uuid.UUID]


class ScanTriggerResponse(BaseModel):
    task_run_id: uuid.UUID


class SoftwareIngestRequest(BaseModel):
    """Сырые данные от внешнего запуска ansible/scan_software.yaml — парсинг происходит на бэкенде."""

    host_id: uuid.UUID
    get_package_raw: str = ""
    choco_raw: str = ""
