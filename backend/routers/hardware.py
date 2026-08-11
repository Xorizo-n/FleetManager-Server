import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user
from models.host import Host, HostStatus
from models.user import User

router = APIRouter(prefix="/hardware", tags=["hardware"])


class HostHardwareOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hostname: str | None
    ip_address: str | None
    status: HostStatus
    hw_manufacturer: str | None
    hw_model: str | None
    hw_serial_number: str | None
    hw_os_caption: str | None
    hw_processor: str | None
    hw_total_memory_bytes: int | None


@router.get("", response_model=list[HostHardwareOut])
def list_hardware(
    search: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(Host).where(
        or_(Host.hw_processor.isnot(None), Host.hw_model.isnot(None))
    )
    if search:
        like = f"%{search}%"
        query = query.where(
            Host.hostname.ilike(like)
            | Host.hw_manufacturer.ilike(like)
            | Host.hw_model.ilike(like)
            | Host.hw_processor.ilike(like)
        )
    return db.execute(query.order_by(Host.hostname)).scalars().all()
