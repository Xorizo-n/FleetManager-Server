import csv
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_roles
from models.host import Host, HostGroup, HostOS
from models.task import TaskRun, TaskStatus, TaskType
from models.user import User, UserRole
from config import settings
from schemas.host import (
    HostCreate,
    HostUpdate,
    HostOut,
    HostGroupCreate,
    HostGroupOut,
    CsvImportResult,
)
from services.audit import record_audit
from services.inventory_generator import build_inventory_ini
from schemas.task import TaskRunOut

router = APIRouter(prefix="/hosts", tags=["hosts"])

EDITOR_ROLES = (UserRole.admin, UserRole.operator)


@router.get("", response_model=list[HostOut])
def list_hosts(
    group_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(Host)
    if group_id:
        query = query.where(Host.group_id == group_id)
    return db.execute(query.order_by(Host.hostname)).scalars().all()


@router.get("/inventory", response_class=PlainTextResponse)
def get_inventory(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return build_inventory_ini(db)


@router.get("/groups", response_model=list[HostGroupOut])
def list_groups(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.execute(select(HostGroup).order_by(HostGroup.name)).scalars().all()


@router.post("/groups", response_model=HostGroupOut, status_code=status.HTTP_201_CREATED)
def create_group(
    payload: HostGroupCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    group = HostGroup(**payload.model_dump())
    db.add(group)
    db.commit()
    db.refresh(group)
    record_audit(db, user.id, "host_group.create", group.name, request)
    return group


@router.post("", response_model=HostOut, status_code=status.HTTP_201_CREATED)
def create_host(
    payload: HostCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    host_data = payload.model_dump()
    if host_data.get("ssh_port") is None:
        host_data["ssh_port"] = settings.ansible_ssh_port
    host = Host(**host_data)
    db.add(host)
    db.commit()
    db.refresh(host)
    record_audit(db, user.id, "host.create", f"{host.hostname} ({host.ip_address})", request)
    return host


@router.post("/{host_id}/diagnostics", response_model=TaskRunOut, status_code=status.HTTP_202_ACCEPTED)
def start_host_diagnostic(
    host_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    host = db.get(Host, host_id)
    if host is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Хост не найден")

    task_run = TaskRun(
        task_type=TaskType.host_diagnostic,
        host_ids=[str(host.id)],
        status=TaskStatus.queued,
        created_by=user.id,
    )
    db.add(task_run)
    db.commit()
    db.refresh(task_run)

    from services.host_diagnostics import run_host_diagnostic

    run_host_diagnostic.delay(str(task_run.id))
    record_audit(db, user.id, "host.diagnostic", host.hostname or host.ip_address, request)
    return task_run


@router.patch("/{host_id}", response_model=HostOut)
def update_host(
    host_id: uuid.UUID,
    payload: HostUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    host = db.get(Host, host_id)
    if host is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Хост не найден")

    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "ssh_port" and value is None:
            continue
        setattr(host, field, value)

    db.commit()
    db.refresh(host)
    record_audit(db, user.id, "host.update", host.hostname, request)
    return host


@router.delete("/{host_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_host(
    host_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    host = db.get(Host, host_id)
    if host is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Хост не найден")

    db.delete(host)
    db.commit()
    record_audit(db, user.id, "host.delete", host.hostname, request)


@router.post("/import-csv", response_model=CsvImportResult)
def import_csv(
    request: Request,
    file: UploadFile,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    """Ожидается CSV с колонками: ip_address,hostname,os,group,comment"""
    content = file.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))

    created = 0
    skipped = 0
    errors: list[str] = []

    group_cache: dict[str, HostGroup] = {}

    for i, row in enumerate(reader, start=2):
        try:
            ip_address = row["ip_address"].strip()
            hostname = row["hostname"].strip()
            os_value = row["os"].strip()
            group_name = (row.get("group") or "").strip()

            if not ip_address or not hostname:
                errors.append(f"Строка {i}: пустой ip_address или hostname")
                skipped += 1
                continue

            try:
                os_enum = HostOS(os_value)
            except ValueError:
                errors.append(f"Строка {i}: неизвестная ОС '{os_value}'")
                skipped += 1
                continue

            existing = db.execute(
                select(Host).where(Host.ip_address == ip_address, Host.hostname == hostname)
            ).scalar_one_or_none()
            if existing:
                skipped += 1
                continue

            group = None
            if group_name:
                group = group_cache.get(group_name)
                if group is None:
                    group = db.execute(select(HostGroup).where(HostGroup.name == group_name)).scalar_one_or_none()
                    if group is None:
                        group = HostGroup(name=group_name)
                        db.add(group)
                        db.flush()
                    group_cache[group_name] = group

            db.add(Host(
                ip_address=ip_address,
                hostname=hostname,
                os=os_enum,
                group_id=group.id if group else None,
                comment=row.get("comment") or None,
            ))
            created += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Строка {i}: {exc}")
            skipped += 1

    db.commit()
    record_audit(db, user.id, "host.import_csv", f"created={created} skipped={skipped}", request)
    return CsvImportResult(created=created, skipped=skipped, errors=errors)
