import csv
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_roles
from models.credential import Credential
from models.host import Host, HostGroup, HostOS
from models.task import TaskRun, TaskStatus, TaskType
from models.user import User, UserRole
from schemas.host import (
    HostCreate,
    HostUpdate,
    HostOut,
    HostGroupCreate,
    HostGroupOut,
    HostGroupAssignRequest,
    HostGroupUnassignRequest,
    HostGroupUpdate,
    HostBulkDeleteRequest,
    AccessChangeRequest,
    AccessChangeResult,
    CsvImportResult,
)
from schemas.task import TaskRunOut
from services.audit import record_audit
from services.inventory_generator import build_inventory_ini
from services.host_target import normalize_host_address, resolve_host_target
from services.host_diagnostics import run_host_diagnostic
from services.host_grouping import find_group_by_name
from services.credential_rules import ssh_credential_error
from services import access_change

router = APIRouter(prefix="/hosts", tags=["hosts"])


def _require_ssh_credential(db: Session, credential_id) -> None:
    """A credential assigned to a host or group must work for SSH (see services/credential_rules.py)."""
    if credential_id is None:
        return
    credential = db.get(Credential, credential_id)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential не найден")
    error = ssh_credential_error(credential)
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

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

    task = TaskRun(
        task_type=TaskType.host_diagnostic,
        host_ids=[str(host_id)],
        status=TaskStatus.queued,
        created_by=user.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    run_host_diagnostic.delay(str(task.id))
    record_audit(db, user.id, "host.diagnostic", str(host_id), request)
    return task


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
    if payload.parent_id is not None and db.get(HostGroup, payload.parent_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Родительская группа не найдена")
    group = HostGroup(**payload.model_dump())
    db.add(group)
    db.commit()
    db.refresh(group)
    record_audit(db, user.id, "host_group.create", group.name, request)
    return group


@router.patch("/groups/{group_id}", response_model=HostGroupOut)
def update_group(
    group_id: uuid.UUID,
    payload: HostGroupUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    group = db.get(HostGroup, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Группа не найдена")

    values = payload.model_dump(exclude_unset=True)
    if "name" in values:
        if group.is_auto:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Автоматическую группу переименовать нельзя: имя задаёт схема имён ПК")
        if not values["name"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Имя группы не может быть пустым")
    if "credential_id" in values and values["credential_id"] != group.credential_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Учётка SSH меняется через POST /hosts/access-changes: он сначала проверяет вход новыми данными")
    values.pop("credential_id", None)
    for field, value in values.items():
        setattr(group, field, value)

    db.commit()
    db.refresh(group)
    record_audit(db, user.id, "host_group.update", group.name, request)
    return group


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    group_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    group = db.get(HostGroup, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Группа не найдена")
    if group.is_auto:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Автоматическую группу удалить нельзя: сервер создаст её заново")
    # ПК группы остаются без группы, подгруппы поднимаются на уровень выше (ondelete SET NULL)
    db.delete(group)
    db.commit()
    record_audit(db, user.id, "host_group.delete", group.name, request)


def _refuse_unverified_move(db: Session, host_ids, group_id) -> None:
    """Moving hosts that inherit their credential from the group may change how SSH logs in."""
    plans = access_change.plan_move(access_change.host_rows(db, host_ids), group_id, access_change.load_groups(db))
    changing = sum(1 for plan in plans if plan.needs_check)
    if changing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"У {changing} ПК при переносе сменится учётка SSH: перенос идёт через POST /hosts/access-changes, он проверяет вход",
        )


@router.post("/access-changes", response_model=AccessChangeResult)
def change_access(
    payload: AccessChangeRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    """Changes the SSH credential of hosts (their own, their group's, or by moving them to
    another group). Hosts whose credential changes are first checked with an SSH login in
    a background task; the change is kept only where the login succeeds."""
    if payload.host_ids:
        found = set(db.execute(select(Host.id).where(Host.id.in_(payload.host_ids))).scalars().all())
        if len(found) != len(set(payload.host_ids)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Один или несколько хостов не найдены")
    if payload.group_id is not None and db.get(HostGroup, payload.group_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Группа не найдена")
    if payload.action != access_change.MOVE_TO_GROUP:
        _require_ssh_credential(db, payload.credential_id)

    spec = {
        "action": payload.action,
        "host_ids": [str(h) for h in payload.host_ids],
        "group_id": str(payload.group_id) if payload.group_id else None,
        "group_name": payload.group_name,
        "credential_id": str(payload.credential_id) if payload.credential_id else None,
    }
    plans = access_change.build_plan(db, spec)
    skipped = sum(1 for plan in plans if plan.skip_reason)
    checks = [plan for plan in plans if plan.needs_check]
    record_audit(db, user.id, f"host_access.{payload.action}", f"hosts={len(plans)} checks={len(checks)}", request)

    if not checks:
        # Учётка ни у кого не меняется — проверять нечего, изменение применяется сразу
        summary = access_change.apply_change(db, spec, plans, passed=set())
        return AccessChangeResult(task=None, applied=summary["applied"], to_check=0, skipped=skipped)

    task = TaskRun(
        task_type=TaskType.access_change,
        host_ids=[str(plan.host_id) for plan in checks],
        extra_vars=spec,
        status=TaskStatus.queued,
        created_by=user.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    access_change.run_access_change.delay(str(task.id))
    return AccessChangeResult(task=TaskRunOut.model_validate(task), applied=0, to_check=len(checks), skipped=skipped)


@router.post("/groups/assign", response_model=HostGroupOut)
def assign_hosts_to_group(
    payload: HostGroupAssignRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    if payload.group_id:
        group = db.get(HostGroup, payload.group_id)
        if group is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Группа не найдена")
    else:
        group = find_group_by_name(db, payload.group_name)
        if group is None:
            group = HostGroup(name=payload.group_name)
            db.add(group)
            db.flush()

    hosts = db.execute(select(Host).where(Host.id.in_(payload.host_ids))).scalars().all()
    found_ids = {host.id for host in hosts}
    missing_ids = [host_id for host_id in payload.host_ids if host_id not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Один или несколько хостов не найдены")
    _refuse_unverified_move(db, payload.host_ids, group.id)

    for host in hosts:
        host.group_id = group.id
    db.commit()
    db.refresh(group)
    record_audit(db, user.id, "host_group.assign", f"group={group.name} hosts={len(hosts)}", request)
    return group


@router.post("/groups/unassign", status_code=status.HTTP_200_OK)
def unassign_hosts_from_group(
    payload: HostGroupUnassignRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    hosts = db.execute(select(Host).where(Host.id.in_(payload.host_ids))).scalars().all()
    found_ids = {host.id for host in hosts}
    missing_ids = [host_id for host_id in payload.host_ids if host_id not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Один или несколько хостов не найдены")
    _refuse_unverified_move(db, payload.host_ids, None)

    for host in hosts:
        host.group_id = None
    db.commit()
    record_audit(db, user.id, "host_group.unassign", f"hosts={len(hosts)}", request)
    return {"unassigned": len(hosts)}


@router.post("", response_model=HostOut, status_code=status.HTTP_201_CREATED)
def create_host(
    payload: HostCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    host_values = payload.model_dump()
    resolve_host_target(host_values.get("hostname"), host_values.get("ip_address"))
    _require_ssh_credential(db, host_values.get("credential_id"))
    host = Host(**host_values)
    db.add(host)
    db.commit()
    db.refresh(host)
    record_audit(db, user.id, "host.create", f"{host.hostname} ({host.ip_address})", request)
    return host


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

    values = payload.model_dump(exclude_unset=True)
    resolve_host_target(values.get("hostname", host.hostname), values.get("ip_address", host.ip_address))
    if "credential_id" in values and values["credential_id"] != host.credential_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Учётка SSH меняется через POST /hosts/access-changes: он сначала проверяет вход новыми данными")
    if "group_id" in values and values["group_id"] != host.group_id:
        _refuse_unverified_move(db, [host.id], values["group_id"])
    for field, value in values.items():
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


@router.post("/delete", status_code=status.HTTP_200_OK)
def delete_hosts(
    payload: HostBulkDeleteRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    hosts = db.execute(select(Host).where(Host.id.in_(payload.host_ids))).scalars().all()
    for host in hosts:
        db.delete(host)
    db.commit()
    record_audit(db, user.id, "host.delete_bulk", f"hosts={len(hosts)}", request)
    return {"deleted": len(hosts)}


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
            ip_address = normalize_host_address(row.get("ip_address"))
            hostname = normalize_host_address(row.get("hostname"))
            os_value = row["os"].strip()
            group_name = (row.get("group") or "").strip()

            try:
                resolve_host_target(hostname, ip_address)
            except ValueError:
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
                    group = find_group_by_name(db, group_name)
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
