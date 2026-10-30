import ipaddress
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from database import get_db
from dependencies import require_roles
from models.printer import Printer
from models.user import User, UserRole
from services.audit import record_audit
from services.crypto import encrypt_secret
from services.printer_monitor import poll_printer
from services.printer_discovery import discovery_status, enqueue_discovery

router = APIRouter(prefix="/printers", tags=["printers"])
editors = require_roles(UserRole.admin, UserRole.operator)
readers = require_roles(UserRole.admin, UserRole.operator, UserRole.viewer)

class PrinterInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    address: str
    location: str | None = Field(default=None, max_length=255)
    community: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        value = value.strip()
        if not value: raise ValueError("Укажите название")
        return value

    @field_validator("address")
    @classmethod
    def valid_address(cls, value):
        try: ip = ipaddress.IPv4Address(value.strip())
        except ValueError: raise ValueError("Укажите IPv4-адрес")
        if ip.is_loopback or ip.is_multicast or ip.is_unspecified or ip.is_link_local or ip.is_reserved:
            raise ValueError("Укажите маршрутизируемый IPv4-адрес")
        return str(ip)

class PrinterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    address: str
    location: str | None
    status: str
    last_checked_at: datetime | None
    last_seen_at: datetime | None
    data: dict | None

def get_printer(db, printer_id):
    printer = db.get(Printer, printer_id)
    if printer is None: raise HTTPException(404, "Принтер не найден")
    return printer

def commit(db):
    try: db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Принтер с таким адресом уже добавлен")

@router.get("", response_model=list[PrinterOut])
def list_printers(db: Session = Depends(get_db), _: User = Depends(readers)):
    return db.query(Printer).order_by(Printer.name).all()

@router.post("", response_model=PrinterOut, status_code=201)
def create_printer(payload: PrinterInput, request: Request, db: Session = Depends(get_db), user: User = Depends(editors)):
    printer = Printer(name=payload.name, address=payload.address, location=payload.location, community_encrypted=encrypt_secret(payload.community or "public"))
    db.add(printer); commit(db); db.refresh(printer)
    record_audit(db, user.id, "printer.create", printer.name, request)
    return printer

@router.put("/{printer_id}", response_model=PrinterOut)
def update_printer(printer_id: uuid.UUID, payload: PrinterInput, request: Request, db: Session = Depends(get_db), user: User = Depends(editors)):
    printer = get_printer(db, printer_id)
    changed_target = printer.address != payload.address or payload.community is not None
    printer.name, printer.address, printer.location = payload.name, payload.address, payload.location
    if payload.community is not None: printer.community_encrypted = encrypt_secret(payload.community)
    if changed_target:
        printer.status = "unknown"; printer.data = None; printer.last_checked_at = None; printer.last_seen_at = None
    commit(db); db.refresh(printer)
    record_audit(db, user.id, "printer.update", printer.name, request)
    return printer

@router.delete("/{printer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_printer(printer_id: uuid.UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(editors)):
    printer = get_printer(db, printer_id); name = printer.name
    db.delete(printer); db.commit(); record_audit(db, user.id, "printer.delete", name, request)

@router.get("/discovery/status")
def get_discovery_status(_: User = Depends(readers)):
    return discovery_status()

@router.post("/discovery", status_code=202)
def start_discovery(request: Request, db: Session = Depends(get_db), user: User = Depends(editors)):
    if not enqueue_discovery(): raise HTTPException(409, "Поиск уже выполняется или ожидает запуска")
    record_audit(db, user.id, "printer.discovery", "Ручной поиск принтеров", request)
    return {"queued": True}

@router.post("/{printer_id}/poll", status_code=202)
def request_poll(printer_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(editors)):
    get_printer(db, printer_id)
    poll_printer.delay(str(printer_id))
    return {"queued": True}
