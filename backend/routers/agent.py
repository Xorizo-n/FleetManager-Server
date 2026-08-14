import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from database import get_db
from config import settings
from dependencies import get_current_user, require_roles
from models.agent import AgentAlert, AgentEnrollmentToken
from models.credential import Credential, CredentialType
from models.host import Host, HostStatus
from models.software import InstallMethod, SoftwareItem, SoftwareStatus
from models.task import TaskRun, TaskStatus, TaskType
from models.user import User, UserRole
from schemas.agent import (
    AgentAlertOut,
    AgentAlertRequest,
    AgentEnrollmentTokenCreate,
    AgentEnrollmentTokenOut,
    AgentEnrollmentTokenResponse,
    AgentHeartbeatRequest,
    AgentHostSelection,
    AgentHostVersionOut,
    AgentOfflineRequest,
    AgentRegisterRequest,
    AgentRegisterResponse,
    AgentStatusOut,
    AgentUninstallRequest,
    AgentVersionOverviewOut,
)
from schemas.task import TaskRunOut
from services.agent_auth import hash_agent_token, issue_agent_token
from services.agent_ssh import generate_agent_keypair
from services.agent_update import run_agent_update, run_agent_version_scan
from services.agent_version import (
    INSTALLER_FILENAME,
    STATUS_OUTDATED,
    STATUS_UNKNOWN,
    agent_version_from_software,
    available_agent_version,
    installer_path,
    normalize_version,
    version_status,
)
from services.audit import record_audit
from services.crypto import encrypt_secret

router = APIRouter(prefix="/agent", tags=["agent"])
bearer = HTTPBearer(auto_error=False)

MAINTENANCE_ROLES = (UserRole.admin, UserRole.operator)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_agent_host(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Host:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Agent bearer token is required")
    token_hash = hash_agent_token(credentials.credentials)
    host = db.execute(select(Host).where(Host.agent_token_hash == token_hash)).scalar_one_or_none()
    if host is None or host.agent_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked agent token")
    return host


def _check_machine(host: Host, machine_id: uuid.UUID) -> None:
    if host.agent_id != machine_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Machine id does not match agent token")


def _install_method(source: str) -> InstallMethod:
    normalized = source.strip().lower()
    if normalized == "chocolatey":
        return InstallMethod.chocolatey
    if normalized == "winget":
        return InstallMethod.winget
    if normalized in {"msi", "registry"}:
        return InstallMethod.msi
    return InstallMethod.other


@router.post("/enrollment-tokens", response_model=AgentEnrollmentTokenResponse, status_code=status.HTTP_201_CREATED)
def create_enrollment_token(
    payload: AgentEnrollmentTokenCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin)),
):
    raw_token = issue_agent_token()
    token = AgentEnrollmentToken(
        name=payload.name,
        token_hash=hash_agent_token(raw_token),
        created_by=user.id,
        expires_at=payload.expires_at,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return AgentEnrollmentTokenResponse(
        id=token.id,
        name=token.name,
        expires_at=token.expires_at,
        is_active=token.is_active,
        raw_token=raw_token,
    )


@router.get("/enrollment-tokens", response_model=list[AgentEnrollmentTokenOut])
def list_enrollment_tokens(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    return db.execute(
        select(AgentEnrollmentToken).order_by(AgentEnrollmentToken.created_at.desc())
    ).scalars().all()


@router.delete("/enrollment-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_enrollment_token(
    token_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    token = db.get(AgentEnrollmentToken, token_id)
    if token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enrollment token not found")
    token.is_active = False
    db.commit()


@router.post("/register", response_model=AgentRegisterResponse)
def register_agent(payload: AgentRegisterRequest, db: Session = Depends(get_db)):
    now = _now()
    enrollment = db.execute(
        select(AgentEnrollmentToken).where(AgentEnrollmentToken.token_hash == hash_agent_token(payload.enrollment_token))
    ).scalar_one_or_none()
    if enrollment is None or not enrollment.is_active or (enrollment.expires_at and enrollment.expires_at <= now):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired enrollment token")
    if not payload.hostname and not payload.ip_address:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="hostname or ip_address is required")

    host = db.execute(select(Host).where(Host.agent_id == payload.machine_id)).scalar_one_or_none()
    matched_existing_agent = host is not None
    if host is None and payload.hostname:
        host = db.execute(
            select(Host).where(Host.agent_id.is_(None), Host.hostname == payload.hostname)
        ).scalar_one_or_none()
    if host is None and payload.ip_address:
        host = db.execute(
            select(Host).where(Host.agent_id.is_(None), Host.ip_address == payload.ip_address)
        ).scalar_one_or_none()
    raw_agent_token = issue_agent_token()
    ssh_public_key: str | None = None
    ssh_login: str | None = payload.ssh_login or "Administrator"
    if host is None:
        host = Host(
            agent_id=payload.machine_id,
            agent_token_hash=hash_agent_token(raw_agent_token),
            hostname=payload.hostname,
            ip_address=payload.ip_address,
            os=payload.os,
            status=HostStatus.online,
            last_seen_at=now,
            last_checked_at=now,
            is_agent_managed=True,
            ssh_port=payload.ssh_port or settings.ansible_ssh_port,
            agent_version=normalize_version(payload.agent_version),
            agent_version_checked_at=now if payload.agent_version else None,
        )
        db.add(host)
    else:
        # Hosts created by older agent versions predate is_agent_managed. If the
        # machine id already identifies the host, restore the marker so a later
        # uninstall can remove that automatically created host completely.
        if matched_existing_agent:
            host.is_agent_managed = True
        host.agent_token_hash = hash_agent_token(raw_agent_token)
        host.hostname = payload.hostname or host.hostname
        host.ip_address = payload.ip_address or host.ip_address
        host.os = payload.os
        if payload.ssh_port:
            host.ssh_port = payload.ssh_port
        host.status = HostStatus.online
        host.last_seen_at = now
        host.last_checked_at = now
        if payload.agent_version:
            host.agent_version = normalize_version(payload.agent_version)
            host.agent_version_checked_at = now

    credential = db.get(Credential, host.credential_id) if host.credential_id else None
    if credential is None:
        private_key, ssh_public_key = generate_agent_keypair()
        credential = Credential(
            name=f"Agent SSH — {host.hostname or payload.machine_id}",
            type=CredentialType.ssh_key,
            login=ssh_login,
            secret_encrypted=encrypt_secret(private_key),
            public_key=ssh_public_key,
            is_agent_managed=True,
        )
        db.add(credential)
        db.flush()
        host.credential_id = credential.id
    elif credential.is_agent_managed:
        if payload.ssh_login:
            credential.login = payload.ssh_login
        ssh_public_key = credential.public_key
        ssh_login = credential.login
    db.commit()
    db.refresh(host)
    return AgentRegisterResponse(
        agent_id=host.agent_id,
        agent_token=raw_agent_token,
        host_id=host.id,
        hostname=host.hostname,
        ip_address=host.ip_address,
        ssh_public_key=ssh_public_key,
        ssh_login=ssh_login,
    )


@router.post("/heartbeat")
def heartbeat(
    payload: AgentHeartbeatRequest,
    host: Host = Depends(_require_agent_host),
    db: Session = Depends(get_db),
):
    _check_machine(host, payload.machine_id)
    now = _now()
    host.hostname = payload.hostname or host.hostname
    host.ip_address = payload.ip_address or host.ip_address
    host.os = payload.os
    host.status = HostStatus.online
    host.last_seen_at = now
    host.last_checked_at = now
    host.last_shutdown_at = None
    host.hardware_fingerprint = payload.hardware.fingerprint
    host.hw_manufacturer = payload.hardware.manufacturer
    host.hw_model = payload.hardware.model
    host.hw_serial_number = payload.hardware.serial_number
    host.hw_os_caption = payload.hardware.operating_system
    host.hw_processor = payload.hardware.processor
    host.hw_total_memory_bytes = payload.hardware.total_memory_bytes
    if payload.ssh_port:
        host.ssh_port = payload.ssh_port
    if payload.ssh_login and host.credential_id:
        credential = db.get(Credential, host.credential_id)
        if credential is not None and credential.is_agent_managed:
            credential.login = payload.ssh_login

    # Версию присылают только свежие агенты. Для старых она достаётся из их же
    # инвентаризации ПО: установщик регистрирует запись "FleetManager Agent".
    reported_version = normalize_version(payload.agent_version) or agent_version_from_software(
        (item.name, item.version) for item in payload.software
    )
    if reported_version:
        host.agent_version = reported_version
        host.agent_version_checked_at = now

    db.execute(delete(SoftwareItem).where(SoftwareItem.host_id == host.id))
    for item in payload.software:
        db.add(SoftwareItem(
            host_id=host.id,
            name=item.name,
            version=item.version,
            install_method=_install_method(item.source),
            status=SoftwareStatus.installed,
            detected_at=now,
        ))
    db.commit()
    return {"status": "accepted", "host_id": host.id, "last_seen_at": now, "software_count": len(payload.software)}


@router.post("/alerts", response_model=AgentAlertOut, status_code=status.HTTP_201_CREATED)
def create_alert(
    payload: AgentAlertRequest,
    host: Host = Depends(_require_agent_host),
    db: Session = Depends(get_db),
):
    _check_machine(host, payload.machine_id)
    alert = AgentAlert(
        host_id=host.id,
        alert_type=payload.alert_type,
        message=payload.message,
        previous_fingerprint=payload.previous_fingerprint,
        current_fingerprint=payload.current_fingerprint,
    )
    if payload.current_fingerprint:
        host.hardware_fingerprint = payload.current_fingerprint
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


@router.post("/offline")
def mark_offline(
    payload: AgentOfflineRequest,
    host: Host = Depends(_require_agent_host),
    db: Session = Depends(get_db),
):
    _check_machine(host, payload.machine_id)
    host.status = HostStatus.offline
    host.last_shutdown_at = _now()
    db.commit()
    return {"status": "offline", "host_id": host.id}


@router.post("/uninstall")
def uninstall_agent(
    payload: AgentUninstallRequest,
    host: Host = Depends(_require_agent_host),
    db: Session = Depends(get_db),
):
    _check_machine(host, payload.machine_id)
    credential = db.get(Credential, host.credential_id) if host.credential_id else None
    host_id = host.id
    if credential is not None and credential.is_agent_managed:
        host.credential_id = None
        db.delete(credential)
    db.execute(delete(AgentAlert).where(AgentAlert.host_id == host.id))
    if host.is_agent_managed:
        db.delete(host)
    else:
        host.agent_id = None
        host.agent_token_hash = None
        host.hardware_fingerprint = None
        host.last_seen_at = None
        host.last_shutdown_at = _now()
        host.status = HostStatus.offline
    db.commit()
    return {"status": "uninstalled", "host_id": host_id}


@router.get("/installer")
def download_agent_installer(host: Host = Depends(_require_agent_host)):
    """Отдаёт установщик самому хосту по его agent-токену.

    Так удалённое обновление (services/agent_update.py) не требует передавать на
    хост никаких серверных секретов: хост скачивает файл своим токеном.
    """
    path = installer_path()
    if not os.path.isfile(path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Установщик агента ещё не синхронизирован на сервере",
        )
    return FileResponse(path, filename=INSTALLER_FILENAME, media_type="application/octet-stream")


@router.get("/versions", response_model=AgentVersionOverviewOut)
def agent_versions(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Сводка версий агента по всем хостам с агентом."""
    available = available_agent_version()
    hosts = db.execute(select(Host).where(Host.agent_id.isnot(None)).order_by(Host.hostname)).scalars().all()

    entries: list[AgentHostVersionOut] = []
    up_to_date = outdated = unknown = 0
    for host in hosts:
        state = version_status(host.agent_version, available, has_agent=True)
        if state == STATUS_OUTDATED:
            outdated += 1
        elif state == STATUS_UNKNOWN:
            unknown += 1
        else:
            # up_to_date и newer одинаково не требуют обновления.
            up_to_date += 1
        entries.append(AgentHostVersionOut(
            host_id=host.id,
            hostname=host.hostname,
            ip_address=host.ip_address,
            has_agent=True,
            agent_version=host.agent_version,
            version_status=state,
            agent_version_checked_at=host.agent_version_checked_at,
            last_seen_at=host.last_seen_at,
            status=host.status,
        ))

    return AgentVersionOverviewOut(
        available_version=available,
        installer_present=os.path.isfile(installer_path()),
        total_agents=len(entries),
        up_to_date=up_to_date,
        outdated=outdated,
        unknown=unknown,
        hosts=entries,
    )


def _agent_hosts_for(db: Session, host_ids: list[uuid.UUID]) -> list[Host]:
    """Хосты с установленным агентом; пустой список host_ids — все такие хосты."""
    query = select(Host).where(Host.agent_id.isnot(None))
    if host_ids:
        query = query.where(Host.id.in_(host_ids))
    hosts = db.execute(query).scalars().all()

    if host_ids:
        missing = set(host_ids) - {host.id for host in hosts}
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Хост не найден или на нём нет зарегистрированного агента",
            )
    if not hosts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нет хостов с установленным агентом")
    return hosts


def _queue_agent_task(
    db: Session,
    user: User,
    request: Request,
    hosts: list[Host],
    task_type: TaskType,
    audit_action: str,
) -> TaskRun:
    task = TaskRun(
        task_type=task_type,
        host_ids=[str(host.id) for host in hosts],
        status=TaskStatus.queued,
        created_by=user.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    record_audit(db, user.id, audit_action, f"hosts={len(hosts)}", request)
    return task


@router.post("/version-scan", response_model=TaskRunOut, status_code=status.HTTP_202_ACCEPTED)
def start_agent_version_scan(
    payload: AgentHostSelection,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MAINTENANCE_ROLES)),
):
    """Проверяет по SSH, какая версия агента реально установлена на хостах."""
    hosts = _agent_hosts_for(db, payload.host_ids)
    task = _queue_agent_task(db, user, request, hosts, TaskType.agent_version_scan, "agent.version_scan")
    run_agent_version_scan.delay(str(task.id))
    return task


@router.post("/update", response_model=TaskRunOut, status_code=status.HTTP_202_ACCEPTED)
def start_agent_update(
    payload: AgentHostSelection,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MAINTENANCE_ROLES)),
):
    """Ставит актуальный установщик агента поверх текущей установки на хостах."""
    if not os.path.isfile(installer_path()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Установщик агента отсутствует: сначала синхронизируйте его с GitHub Releases",
        )
    hosts = _agent_hosts_for(db, payload.host_ids)
    task = _queue_agent_task(db, user, request, hosts, TaskType.agent_update, "agent.update")
    run_agent_update.delay(str(task.id))
    return task


@router.get("/status/{agent_id}", response_model=AgentStatusOut)
def agent_status(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.operator)),
):
    host = db.execute(select(Host).where(Host.agent_id == agent_id)).scalar_one_or_none()
    if host is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    alerts = db.execute(
        select(AgentAlert).where(AgentAlert.host_id == host.id).order_by(AgentAlert.created_at.desc()).limit(50)
    ).scalars().all()
    return AgentStatusOut(
        agent_id=host.agent_id,
        host_id=host.id,
        hostname=host.hostname,
        ip_address=host.ip_address,
        os=host.os,
        status=host.status,
        last_seen_at=host.last_seen_at,
        last_shutdown_at=host.last_shutdown_at,
        hardware_fingerprint=host.hardware_fingerprint,
        alerts=alerts,
    )
