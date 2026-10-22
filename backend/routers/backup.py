"""Настройки копий вне ВМ и их журнал (services/offsite_backup.py). Только администратор."""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_roles
from models.backup import BackupRun, BackupSettings
from models.user import User, UserRole
from services import offsite_backup as ob
from services.audit import record_audit
from services.crypto import encrypt_secret

router = APIRouter(prefix="/settings/backup", tags=["settings"])
admin_only = require_roles(UserRole.admin)

MIN_REPO_PASSWORD = 12


class BackupSettingsIn(BaseModel):
    enabled: bool
    sftp_host: str = Field(default="", max_length=255)
    sftp_port: int = Field(default=22, ge=1, le=65535)
    sftp_user: str = Field(default="", max_length=128)
    sftp_path: str = Field(default="", max_length=512)
    # None — оставить сохранённый, "" — удалить
    sftp_password: str | None = Field(default=None, max_length=256)
    repo_password: str | None = Field(default=None, max_length=256)

    @field_validator("sftp_host", "sftp_user", "sftp_path")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if any(c in value for c in " \t\n'\"`$;|&<>"):
            raise ValueError("Без пробелов, кавычек и спецсимволов оболочки")
        return value

    @field_validator("sftp_path")
    @classmethod
    def _absolute(cls, value: str) -> str:
        if value and not value.startswith("/"):
            raise ValueError("Путь в хранилище — от корня: /srv/backup/fleet-manager")
        return value.rstrip("/") or value


class RunIn(BaseModel):
    kind: str

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        if value not in ob.KINDS:
            raise ValueError("kind: db, share или check")
        return value


def _run_out(run: BackupRun) -> dict:
    return {
        "id": run.id, "kind": run.kind, "started_at": run.started_at, "finished_at": run.finished_at, "ok": run.ok,
        "message": run.message, "snapshot_ids": run.snapshot_ids, "bytes_added": run.bytes_added, "details": run.details,
    }


def _out(db: Session, row: BackupSettings | None) -> dict:
    runs = db.execute(select(BackupRun).order_by(BackupRun.started_at.desc()).limit(30)).scalars().all()
    last = {kind: ob._last_ok(db, kind) for kind in ob.KINDS}
    return {
        "enabled": bool(row and row.enabled),
        "sftp_host": row.sftp_host if row else "",
        "sftp_port": row.sftp_port if row else 22,
        "sftp_user": row.sftp_user if row else "",
        "sftp_path": row.sftp_path if row else "",
        "has_sftp_password": bool(row and row.sftp_password_encrypted),
        "has_repo_password": bool(row and row.repo_password_encrypted),
        "host_key_fingerprint": ob.fingerprint(row.host_key) if row else None,
        "initialized": bool(row and row.initialized),
        "updated_at": row.updated_at if row else None,
        "last_ok": {kind: (run.finished_at if run else None) for kind, run in last.items()},
        "runs": [_run_out(run) for run in runs],
    }


def _draft(row: BackupSettings | None, payload: BackupSettingsIn) -> ob.Target:
    saved = ob.target_from_row(row) if row else None
    same_host = saved is not None and (saved.host, saved.port) == (payload.sftp_host, payload.sftp_port)
    return ob.Target(
        host=payload.sftp_host, port=payload.sftp_port, user=payload.sftp_user, path=payload.sftp_path,
        password=(saved.password if saved else "") if payload.sftp_password is None else payload.sftp_password,
        repo_password=(saved.repo_password if saved else "") if payload.repo_password is None else payload.repo_password,
        host_key=saved.host_key if same_host else None,
    )


@router.get("")
def get_settings(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    return _out(db, db.get(BackupSettings, 1))


@router.put("")
def save_settings(payload: BackupSettingsIn, request: Request, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    row = db.get(BackupSettings, 1)
    target = _draft(row, payload)
    if payload.enabled and not all((target.host, target.user, target.path, target.password, target.repo_password)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Для включения нужны адрес, логин, путь, пароль SFTP и пароль шифрования копий")
    if payload.repo_password is not None:
        if row is not None and row.initialized and target.repo_password != ob.target_from_row(row).repo_password:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Хранилище уже создано с другим паролем шифрования — сменить его здесь нельзя")
        if payload.repo_password and len(payload.repo_password) < MIN_REPO_PASSWORD:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Пароль шифрования копий — не короче {MIN_REPO_PASSWORD} символов")

    moved = row is None or (row.sftp_host, row.sftp_port, row.sftp_user, row.sftp_path) != (target.host, target.port, target.user, target.path)
    if row is None:
        row = BackupSettings(id=1)
        db.add(row)
    host_key = target.host_key
    if target.host and not host_key:
        try:
            host_key = ob.scan_host_key(target.host, target.port)  # закрепляется: дальше вход только к этому ключу
        except ob.BackupError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    row.enabled = payload.enabled
    row.sftp_host, row.sftp_port, row.sftp_user, row.sftp_path = target.host, target.port, target.user, target.path
    row.host_key = host_key
    if payload.sftp_password is not None:
        row.sftp_password_encrypted = encrypt_secret(payload.sftp_password) if payload.sftp_password else None
    if payload.repo_password is not None:
        row.repo_password_encrypted = encrypt_secret(payload.repo_password) if payload.repo_password else None
    if moved:
        row.initialized = False
    row.updated_by = admin.id
    db.commit()
    db.refresh(row)
    changes = [f"{'включено' if row.enabled else 'выключено'}", f"{row.sftp_user}@{row.sftp_host}:{row.sftp_port}{row.sftp_path}",
               f"ключ хоста {ob.fingerprint(row.host_key)}"]
    if payload.sftp_password is not None:
        changes.append("пароль SFTP изменён")
    if payload.repo_password is not None:
        changes.append("пароль шифрования копий задан")
    record_audit(db, admin.id, "settings.backup", "; ".join(changes), request)
    return _out(db, row)


@router.post("/check")
def check_settings(payload: BackupSettingsIn, db: Session = Depends(get_db), _: User = Depends(admin_only)):
    """Проверка формы до сохранения: SFTP-вход, пароль шифрования, есть ли уже хранилище."""
    target = _draft(db.get(BackupSettings, 1), payload)
    if not all((target.host, target.user, target.path, target.password)):
        return {"ok": False, "error": "Заполните адрес, логин, путь и пароль SFTP"}
    pinned = bool(target.host_key)
    try:
        target = replace(target, host_key=target.host_key or ob.scan_host_key(target.host, target.port))
        ob.sftp_check(target)
        # Без пароля шифрования проверяется только вход и каталог
        state = ob.repository_state(target) if target.repo_password else None
    except ob.BackupError as exc:
        return {"ok": False, "error": str(exc), "host_key_fingerprint": ob.fingerprint(target.host_key), "host_key_pinned": pinned}
    return {"ok": True, "repository": state, "host_key_fingerprint": ob.fingerprint(target.host_key), "host_key_pinned": pinned}


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
def run_now(payload: RunIn, request: Request, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    row = db.get(BackupSettings, 1)
    if row is None or not row.sftp_host or not row.repo_password_encrypted:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Сначала настройте и сохраните хранилище")
    running = db.execute(select(BackupRun).where(BackupRun.kind == payload.kind, BackupRun.finished_at.is_(None),
                                                 BackupRun.started_at > datetime.now(timezone.utc) - timedelta(hours=13))).scalars().first()
    if running is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Такое копирование уже идёт")
    run = BackupRun(kind=payload.kind, started_by=admin.id)
    db.add(run)
    db.commit()
    ob.run_backup.delay(payload.kind, str(run.id))
    record_audit(db, admin.id, "backup.run", payload.kind, request)
    return _run_out(run)


@router.get("/snapshots")
def list_snapshots(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    """Что лежит в хранилище: последние снимки каждого вида."""
    row = db.get(BackupSettings, 1)
    if row is None or not row.initialized:
        return []
    try:
        data = json.loads(ob.restic(ob.target_from_row(row), "snapshots", "--json", "--host", ob.RESTIC_HOST, timeout=120).stdout or "[]")
    except ob.BackupError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    out = [{"id": s.get("short_id") or s["id"][:8], "time": s.get("time"), "tags": s.get("tags") or [], "paths": s.get("paths") or [],
            "bytes": (s.get("summary") or {}).get("total_bytes_processed")} for s in data]
    return sorted(out, key=lambda s: s["time"] or "", reverse=True)[:60]


