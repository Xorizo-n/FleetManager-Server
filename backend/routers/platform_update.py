"""Admin-only bridge to the host updater; no Docker socket in the application."""
import http.client
import json
import socket

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from dependencies import require_roles
from models.user import User, UserRole
from services.audit import record_audit

router = APIRouter(prefix="/settings/platform", tags=["settings"])
admin_only = require_roles(UserRole.admin)


class InstallIn(BaseModel):
    version: str = Field(pattern=r"^v\d+\.\d+\.\d+$", max_length=40)


class RestoreIn(BaseModel):
    confirm_data_loss: bool


class UpdaterConnection(http.client.HTTPConnection):
    def __init__(self):
        super().__init__("localhost", timeout=40)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(settings.platform_updater_socket)


def call(method, path, body=None):
    connection = UpdaterConnection()
    try:
        connection.request(method, path, json.dumps(body or {}), {"Content-Type": "application/json"})
        response = connection.getresponse()
        data = json.loads(response.read(2 * 1024 * 1024))
        if response.status != 200:
            raise HTTPException(response.status, data.get("detail", "Ошибка службы обновлений"))
        return data
    except (OSError, http.client.HTTPException, ValueError) as exc:
        raise HTTPException(503, "Служба обновления платформы недоступна") from exc
    finally:
        connection.close()


@router.get("")
def get_status(_: User = Depends(admin_only)):
    return call("GET", "/status")


@router.post("/check")
def check(_: User = Depends(admin_only)):
    return call("POST", "/check")


@router.post("/install", status_code=202)
def install(payload: InstallIn, request: Request, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    # Record intent before the updater can stop the database client.
    record_audit(db, admin.id, "platform.install.request", payload.version, request)
    return call("POST", "/install", {"version": payload.version, "actor": str(admin.id)})


@router.post("/restore", status_code=202)
def restore(payload: RestoreIn, request: Request, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    if not payload.confirm_data_loss:
        raise HTTPException(400, "Нужно подтвердить замену БД резервной копией")
    record_audit(db, admin.id, "platform.restore.request", "Подтверждено восстановление БД", request)
    return call("POST", "/restore", {"confirm_data_loss": True, "actor": str(admin.id)})
