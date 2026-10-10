import csv
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_roles
from models.host import Host
from models.software import SoftwareItem, SoftwareHistory, SoftwareStatus
from models.task import TaskRun, TaskType, TaskStatus
from models.user import User, UserRole
from schemas.software import (
    SoftwareItemOut,
    SoftwareHistoryOut,
    SoftwareSummaryItem,
    SoftwarePackageOut,
    SoftwareVersionCount,
    ScanTriggerRequest,
    ScanTriggerResponse,
    SoftwareIngestRequest,
)
from services.audit import record_audit
from services.software_parse import parse_get_package, parse_choco_list
from services.software_sync import sync_host_software
from models.software import InstallMethod

router = APIRouter(prefix="/software", tags=["software"])


_SYSTEM_PREFIXES = [
    # Microsoft / Windows packages (space or dot separator)
    "microsoft ",
    "microsoft.",
    "microsoftwindows.",
    "microsoftcorporationii.",
    "windows ",
    "windows.",
    # Windows Update
    "kb",
    "update for ",
    "security update",
    "hotfix",
    # Runtimes included in Microsoft prefix, but kept explicit for clarity
    "visual c++",
    ".net",
    "directx",
    # Visual Studio installer internals
    "vs_",
    "vcpp_crt",
    "vs script debugging",
    # Windows SDK components
    "winrt intellisense",
    "universal crt",
    "sdk arm64",
    "winappde",
    "wptx64",
    "kits configuration",
    "application verifier",
    "diagnosticshub_",
    "msi development tools",
    "universal general midi",
    # Office Click-to-Run internals
    "office 16 click-to-run",
    "clickonce bootstrapper",
    # System UWP services
    "ncsiuwpapp",
    "mdodrmcpfilter",
]

# UUID/GUID pattern — системные AppX package ID вида «1527c705-839a-4832-...»
_GUID_REGEX = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'


def without_system_software(query):
    """Скрывает системное ПО Microsoft/Windows и AppX-пакеты с GUID вместо имени."""
    for prefix in _SYSTEM_PREFIXES:
        query = query.where(~SoftwareItem.name.ilike(f"{prefix}%"))
    return query.where(~SoftwareItem.name.op("~*")(_GUID_REGEX))


@router.get("", response_model=list[SoftwareItemOut])
def list_software(
    host_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    name: str | None = None,
    status_filter: SoftwareStatus | None = None,
    exclude_system: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(SoftwareItem).join(Host, SoftwareItem.host_id == Host.id)
    if host_id:
        query = query.where(SoftwareItem.host_id == host_id)
    if group_id:
        query = query.where(Host.group_id == group_id)
    if name:
        query = query.where(SoftwareItem.name.ilike(f"%{name}%"))
    if status_filter:
        query = query.where(SoftwareItem.status == status_filter)
    if exclude_system:
        query = without_system_software(query)
    return db.execute(query.order_by(SoftwareItem.name)).scalars().all()


@router.get("/summary", response_model=list[SoftwareSummaryItem])
def software_summary(
    name: str | None = None,
    exclude_system: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = (
        select(SoftwareItem.name, SoftwareItem.version, func.count(func.distinct(SoftwareItem.host_id)))
        .where(SoftwareItem.status == SoftwareStatus.installed)
        .group_by(SoftwareItem.name, SoftwareItem.version)
        .order_by(func.count(func.distinct(SoftwareItem.host_id)).desc())
    )
    if name:
        query = query.where(SoftwareItem.name.ilike(f"%{name}%"))
    if exclude_system:
        query = without_system_software(query)
    rows = db.execute(query).all()
    return [SoftwareSummaryItem(name=r[0], version=r[1], host_count=r[2]) for r in rows]


@router.get("/packages", response_model=list[SoftwarePackageOut])
def software_packages(
    name: str | None = None,
    exclude_system: bool = True,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Каталог ПО: один пакет — одна строка, с числом хостов и разбивкой по версиям."""
    query = (
        select(SoftwareItem.name, SoftwareItem.version, func.count(func.distinct(SoftwareItem.host_id)))
        .where(SoftwareItem.status == SoftwareStatus.installed)
        .group_by(SoftwareItem.name, SoftwareItem.version)
    )
    if name:
        query = query.where(SoftwareItem.name.ilike(f"%{name}%"))
    if exclude_system:
        query = without_system_software(query)
    totals = dict(
        db.execute(
            select(SoftwareItem.name, func.count(func.distinct(SoftwareItem.host_id)))
            .where(SoftwareItem.status == SoftwareStatus.installed)
            .group_by(SoftwareItem.name)
        ).all()
    )
    packages: dict[str, SoftwarePackageOut] = {}
    for package_name, version, host_count in db.execute(query).all():
        package = packages.setdefault(
            package_name, SoftwarePackageOut(name=package_name, host_count=totals.get(package_name, 0), versions=[])
        )
        package.versions.append(SoftwareVersionCount(version=version, host_count=host_count))
    for package in packages.values():
        package.versions.sort(key=lambda item: item.host_count, reverse=True)
    return sorted(packages.values(), key=lambda item: (-item.host_count, item.name.lower()))


@router.get("/package-hosts", response_model=list[SoftwareItemOut])
def software_package_hosts(name: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Хосты, на которых установлен пакет с точно таким именем."""
    query = select(SoftwareItem).where(SoftwareItem.name == name, SoftwareItem.status == SoftwareStatus.installed)
    return db.execute(query.order_by(SoftwareItem.version)).scalars().all()


@router.get("/history", response_model=list[SoftwareHistoryOut])
def software_history(
    host_id: uuid.UUID | None = None,
    name: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(SoftwareHistory)
    if host_id:
        query = query.where(SoftwareHistory.host_id == host_id)
    if name:
        query = query.where(SoftwareHistory.name.ilike(f"%{name}%"))
    return db.execute(query.order_by(SoftwareHistory.changed_at.desc()).limit(500)).scalars().all()


@router.post("/scan", response_model=ScanTriggerResponse)
def trigger_scan(
    payload: ScanTriggerRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin, UserRole.operator)),
):
    from services.software_scanner import scan_software_task

    task_run = TaskRun(
        task_type=TaskType.software_scan,
        host_ids=[str(h) for h in payload.host_ids],
        status=TaskStatus.queued,
        created_by=user.id,
    )
    db.add(task_run)
    db.commit()
    db.refresh(task_run)

    scan_software_task.delay(str(task_run.id))
    record_audit(db, user.id, "software.scan", f"hosts={len(payload.host_ids)}")
    return ScanTriggerResponse(task_run_id=task_run.id)


@router.post("/ingest", status_code=status.HTTP_204_NO_CONTENT)
def ingest_scan_result(
    payload: SoftwareIngestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin, UserRole.operator)),
):
    """Callback-эндпоинт для внешнего запуска ansible/scan_software.yaml (например, через ansible-playbook + uri)."""
    host = db.get(Host, payload.host_id)
    if host is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Хост не найден")

    discovered: dict[str, tuple[str, InstallMethod]] = {}
    for name, version in parse_get_package(payload.get_package_raw):
        discovered[name] = (version, InstallMethod.msi)
    for name, version in parse_choco_list(payload.choco_raw):
        discovered[name] = (version, InstallMethod.chocolatey)

    sync_host_software(db, host, discovered)
    record_audit(db, user.id, "software.ingest", f"{host.hostname}: {len(discovered)} записей")


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.operator))):
    items = db.execute(
        select(SoftwareItem, Host.hostname)
        .join(Host, SoftwareItem.host_id == Host.id)
        .where(SoftwareItem.status == SoftwareStatus.installed)
        .order_by(Host.hostname, SoftwareItem.name)
    ).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["hostname", "name", "version", "install_method", "detected_at"])
    for item, hostname in items:
        writer.writerow([hostname, item.name, item.version, item.install_method.value, item.detected_at.isoformat()])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=software_inventory.csv"},
    )


@router.get("/export.pdf")
def export_pdf(db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.operator))):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    items = db.execute(
        select(SoftwareItem, Host.hostname)
        .join(Host, SoftwareItem.host_id == Host.id)
        .where(SoftwareItem.status == SoftwareStatus.installed)
        .order_by(Host.hostname, SoftwareItem.name)
    ).all()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    data = [["Host", "Software", "Version", "Method"]]
    for item, hostname in items:
        data.append([hostname, item.name, item.version or "", item.install_method.value])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    doc.build([table])

    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=software_inventory.pdf"},
    )
