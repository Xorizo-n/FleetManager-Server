import os
import re
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

import psutil
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user
from models.agent import AgentAlert
from models.host import Host, HostGroup, HostStatus, HostStatusHistory
from models.software import SoftwareItem, SoftwareHistory, SoftwareStatus
from models.task import TaskRun, TaskStatus
from models.user import User
from services.activation import GRACE, UNLICENSED, activation_state
from services.agent_version import STATUS_OUTDATED, available_agent_version, version_status
from routers.software import _GUID_REGEX, _SYSTEM_PREFIXES
from schemas.software import SoftwareHistoryOut, SoftwareSummaryItem
from schemas.task import TaskRunOut

# Агент считается онлайн, если прислал heartbeat не позднее этого интервала назад
HEARTBEAT_TIMEOUT = timedelta(minutes=10)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class HostsSummary(BaseModel):
    total: int
    online: int
    offline: int
    unknown: int


class OnlineTimelinePoint(BaseModel):
    hour: str
    online: int


class WeeklyRunStats(BaseModel):
    day: str
    success: int
    failed: int


@router.get("/hosts-summary", response_model=HostsSummary)
def hosts_summary(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    # cast нужен чтобы enum возвращался как строка при group by
    rows = db.execute(
        select(cast(Host.status, String), func.count()).group_by(Host.status)
    ).all()

    counts = {s.value: 0 for s in HostStatus}
    total = 0
    for status_str, count in rows:
        key = status_str if isinstance(status_str, str) else status_str.value
        if key in counts:
            counts[key] += count
        total += count
    return HostsSummary(total=total, online=counts["online"], offline=counts["offline"], unknown=counts["unknown"])


@router.get("/recent-tasks", response_model=list[TaskRunOut])
def recent_tasks(limit: int = 10, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.execute(select(TaskRun).order_by(TaskRun.created_at.desc()).limit(limit)).scalars().all()


@router.get("/top-software", response_model=list[SoftwareSummaryItem])
def top_software(limit: int = 10, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    # Группируем только по name (не по версии) — один пакет = одна строка
    query = (
        select(SoftwareItem.name, func.count(func.distinct(SoftwareItem.host_id)).label("host_count"))
        .where(SoftwareItem.status == SoftwareStatus.installed)
        .group_by(SoftwareItem.name)
        .order_by(func.count(func.distinct(SoftwareItem.host_id)).desc())
        .limit(limit)
    )
    # Исключаем системное/Microsoft ПО (те же правила что в реестре)
    for prefix in _SYSTEM_PREFIXES:
        query = query.where(~SoftwareItem.name.ilike(f"{prefix}%"))
    query = query.where(~SoftwareItem.name.op("~*")(_GUID_REGEX))

    rows = db.execute(query).all()
    return [SoftwareSummaryItem(name=r[0], version=None, host_count=r[1]) for r in rows]


@router.get("/stale-hosts", response_model=list[str])
def stale_hosts(days: int = 7, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    threshold = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(Host.hostname).where((Host.last_checked_at.is_(None)) | (Host.last_checked_at < threshold))
    ).scalars().all()
    return rows


@router.get("/recent-software-changes", response_model=list[SoftwareHistoryOut])
def recent_software_changes(limit: int = 10, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.execute(select(SoftwareHistory).order_by(SoftwareHistory.changed_at.desc()).limit(limit)).scalars().all()


@router.get("/online-timeline", response_model=list[OnlineTimelinePoint])
def online_timeline(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    # Используем локальное время сервера чтобы метки совпадали с часами пользователя
    now = datetime.now().astimezone()
    since = now - timedelta(hours=24)

    rows = db.execute(
        select(HostStatusHistory.recorded_at, HostStatusHistory.host_id)
        .where(
            HostStatusHistory.recorded_at >= since,
            HostStatusHistory.status == HostStatus.online,
        )
    ).all()

    # Конвертируем в локальное время сервера и группируем по часовому bucket
    buckets: dict[datetime, set] = {}
    for recorded_at, host_id in rows:
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=timezone.utc)
        local_dt = recorded_at.astimezone()
        slot = local_dt.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(slot, set()).add(host_id)

    # Заполняем все 24 часовых слота, включая нулевые
    result = []
    slot = since.replace(minute=0, second=0, microsecond=0)
    end_slot = now.replace(minute=0, second=0, microsecond=0)
    while slot <= end_slot:
        result.append(OnlineTimelinePoint(hour=slot.strftime("%d.%m %H:00"), online=len(buckets.get(slot, set()))))
        slot += timedelta(hours=1)

    return result


@router.get("/weekly-run-stats", response_model=list[WeeklyRunStats])
def weekly_run_stats(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    # Все 7 дней, включая дни без запусков, по локальному времени сервера
    today = datetime.now().astimezone().date()
    days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    since = datetime.combine(days[0], datetime.min.time()).astimezone()
    rows = db.execute(select(TaskRun.created_at, TaskRun.status).where(TaskRun.created_at >= since)).all()

    buckets: dict = {day: {"success": 0, "failed": 0} for day in days}
    for created_at, status_value in rows:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        day = created_at.astimezone().date()
        if day in buckets and status_value.value in ("success", "failed"):
            buckets[day][status_value.value] += 1

    return [WeeklyRunStats(day=day.strftime("%d.%m"), success=v["success"], failed=v["failed"]) for day, v in buckets.items()]


class DiskUsageOut(BaseModel):
    mount: str
    total_gb: float
    used_gb: float
    percent: float


class ServerMetrics(BaseModel):
    cpu_percent: float
    cpu_count: int
    load_avg: list[float]
    mem_total_gb: float
    mem_used_gb: float
    mem_percent: float
    swap_percent: float
    net_sent_mbps: float
    net_recv_mbps: float
    disks: list[DiskUsageOut]
    uptime_seconds: int
    process_count: int


# Предыдущий замер сети — для расчёта скорости по дельте между соседними опросами
_net_prev: dict = {"counters": None, "t": None}


@router.get("/server-metrics", response_model=ServerMetrics)
def server_metrics(_: User = Depends(get_current_user)):
    """Метрики сервера Fleet Manager: CPU, память, сеть, диски, load average, uptime.

    Из контейнера psutil читает /proc, поэтому CPU/память/сеть/uptime — это показатели
    хоста. Диск «/» — это контейнер, /mnt/soft-share — рабочий диск с данными.

    ВАЖНО: эндпоинт НЕ блокируется (никаких sleep), иначе соединение с БД удерживается
    на всё время замера и при частом опросе исчерпывается пул соединений. CPU считаем
    неблокирующим cpu_percent(interval=None), скорость сети — по дельте между опросами.
    """
    # CPU: процент с момента прошлого вызова (psutil хранит состояние между вызовами)
    cpu = psutil.cpu_percent(interval=None)

    # Сеть: скорость по дельте счётчиков между соседними опросами, без sleep
    now_net = psutil.net_io_counters()
    now_t = time.monotonic()
    prev, prev_t = _net_prev["counters"], _net_prev["t"]
    if prev is not None and prev_t is not None:
        dt = max(now_t - prev_t, 0.1)
        sent_mbps = (now_net.bytes_sent - prev.bytes_sent) * 8 / 1_000_000 / dt
        recv_mbps = (now_net.bytes_recv - prev.bytes_recv) * 8 / 1_000_000 / dt
    else:
        sent_mbps = recv_mbps = 0.0
    _net_prev["counters"] = now_net
    _net_prev["t"] = now_t

    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()

    try:
        load = [round(x, 2) for x in os.getloadavg()]
    except (OSError, AttributeError):
        load = []

    disks: list[DiskUsageOut] = []
    for mount in ("/", "/mnt/soft-share"):
        try:
            u = psutil.disk_usage(mount)
            disks.append(DiskUsageOut(mount=mount, total_gb=round(u.total / 1_000_000_000, 1), used_gb=round(u.used / 1_000_000_000, 1), percent=u.percent))
        except (FileNotFoundError, PermissionError, OSError):
            pass

    return ServerMetrics(
        cpu_percent=round(cpu, 1),
        cpu_count=psutil.cpu_count() or 0,
        load_avg=load,
        mem_total_gb=round(vm.total / 1_000_000_000, 1),
        mem_used_gb=round(vm.used / 1_000_000_000, 1),
        mem_percent=vm.percent,
        swap_percent=sw.percent,
        net_sent_mbps=round(sent_mbps, 2),
        net_recv_mbps=round(recv_mbps, 2),
        disks=disks,
        uptime_seconds=int(time.time() - psutil.boot_time()),
        process_count=len(psutil.pids()),
    )


# ---------------------------------------------------------------------------
# Дашборд мониторинга (настенный экран): всё одним запросом. Телевизор опрашивает
# его каждые 15 с, поэтому полный список хостов (968 записей с инвентарём) клиенту не
# отдаём — считаем агрегаты на сервере, читая только нужные столбцы.
# ---------------------------------------------------------------------------


class MonitoringRoom(BaseModel):
    id: uuid.UUID
    name: str
    short_name: str
    total: int
    online: int
    alerts: int
    disk: int
    not_activated: int


class MonitoringFloor(BaseModel):
    name: str | None
    rooms: list[MonitoringRoom]


class MonitoringBuilding(BaseModel):
    id: uuid.UUID
    name: str
    total: int
    online: int
    floors: list[MonitoringFloor]


class MonitoringAlert(BaseModel):
    id: uuid.UUID
    host_id: uuid.UUID
    hostname: str | None
    room: str | None
    alert_type: str
    message: str
    created_at: datetime


class MonitoringOut(BaseModel):
    generated_at: datetime
    total: int
    online: int
    offline: int
    unknown: int
    stale_7d: int
    without_agent: int
    agent_available_version: str | None
    agent_outdated: int
    win_not_activated: int
    office_not_activated: int
    kms_unreachable: int
    disks_critical: int
    tasks_running: int
    tasks_failed_24h: int
    alerts_24h: int
    alerts: list[MonitoringAlert]
    buildings: list[MonitoringBuilding]


_FLOOR_NUMBER = re.compile(r"-?\d+")
_NOT_ACTIVATED = (UNLICENSED, GRACE)  # как notActivated на фронте: не активирован или пробный период


def _floor_key(name: str | None) -> tuple[int, int, str]:
    """Этажи сверху вниз, как в здании; без номера — в конец."""
    if not name:
        return (1, 0, "")
    match = _FLOOR_NUMBER.search(name)
    return (0, -int(match.group()) if match else 0, name)


@router.get("/monitoring", response_model=MonitoringOut)
def monitoring(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)

    groups = {gid: (name, parent) for gid, name, parent in db.execute(select(HostGroup.id, HostGroup.name, HostGroup.parent_id)).all()}
    hosts = db.execute(
        select(Host.id, Host.hostname, Host.group_id, Host.status, Host.agent_id, Host.agent_version,
               Host.disk_alarms, Host.license_activation, Host.last_checked_at)
    ).all()
    alert_rows = db.execute(
        select(AgentAlert.id, AgentAlert.host_id, AgentAlert.alert_type, AgentAlert.message, AgentAlert.created_at)
        .where(AgentAlert.created_at >= day_ago)
        .order_by(AgentAlert.created_at.desc())
    ).all()
    tasks_running = db.execute(
        select(func.count()).select_from(TaskRun).where(TaskRun.status.in_([TaskStatus.queued, TaskStatus.running]))
    ).scalar_one()
    tasks_failed = db.execute(
        select(func.count()).select_from(TaskRun).where(TaskRun.status == TaskStatus.failed, TaskRun.created_at >= day_ago)
    ).scalar_one()

    def path(gid) -> list:
        """Цепочка групп от корня (корпус) до gid."""
        chain, seen = [], set()
        while gid is not None and gid in groups and gid not in seen:
            seen.add(gid)
            chain.append(gid)
            gid = groups[gid][1]
        return list(reversed(chain))

    available = available_agent_version()
    alerts_by_host = Counter(row.host_id for row in alert_rows)
    host_info = {}
    rooms: dict = {}
    totals = Counter()

    for h in hosts:
        la = h.license_activation if isinstance(h.license_activation, dict) else None
        win_bad = activation_state(la, "windows") in _NOT_ACTIVATED
        office_bad = activation_state(la, "office") in _NOT_ACTIVATED
        disk_bad = bool(h.disk_alarms)
        checked = h.last_checked_at
        if checked is not None and checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)

        totals["total"] += 1
        totals[h.status.value if h.status else "unknown"] += 1
        totals["stale"] += checked is None or checked < week_ago
        totals["win"] += win_bad
        totals["office"] += office_bad
        totals["kms"] += bool(la and (la.get("kms_probe") or {}).get("reachable") is False)
        totals["disk"] += disk_bad
        if h.agent_id is None:
            totals["no_agent"] += 1
        elif version_status(h.agent_version, available, has_agent=True) == STATUS_OUTDATED:
            totals["outdated"] += 1

        host_info[h.id] = (h.hostname, groups[h.group_id][0] if h.group_id in groups else None)
        if h.group_id in groups:
            room = rooms.setdefault(h.group_id, Counter())
            room["total"] += 1
            room["online"] += h.status == HostStatus.online
            room["alerts"] += alerts_by_host.get(h.id, 0)
            room["disk"] += disk_bad
            room["not_activated"] += win_bad or office_bad

    # Корпус -> этаж -> аудитория: корпус — корень дерева, этаж — второй уровень (если есть)
    buildings: dict = {}
    for gid, stats in rooms.items():
        chain = path(gid)
        root = chain[0]
        floor = groups[chain[1]][0] if len(chain) >= 3 else None
        building_name = groups[root][0]
        name = groups[gid][0]
        prefix = f"{building_name}-"
        short = name[len(prefix):] if name.startswith(prefix) else name
        b = buildings.setdefault(root, {"name": building_name, "floors": {}})
        b["floors"].setdefault(floor, []).append(MonitoringRoom(
            id=gid, name=name, short_name=short, total=stats["total"], online=stats["online"],
            alerts=stats["alerts"], disk=stats["disk"], not_activated=stats["not_activated"],
        ))

    building_out = []
    for root, b in buildings.items():
        floors = [
            MonitoringFloor(name=floor, rooms=sorted(room_list, key=lambda r: r.short_name))
            for floor, room_list in sorted(b["floors"].items(), key=lambda item: _floor_key(item[0]))
        ]
        building_out.append(MonitoringBuilding(
            id=root, name=b["name"], floors=floors,
            total=sum(r.total for f in floors for r in f.rooms),
            online=sum(r.online for f in floors for r in f.rooms),
        ))
    building_out.sort(key=lambda b: -b.total)

    alerts = [
        MonitoringAlert(
            id=row.id, host_id=row.host_id, hostname=host_info.get(row.host_id, (None, None))[0],
            room=host_info.get(row.host_id, (None, None))[1], alert_type=row.alert_type,
            message=row.message, created_at=row.created_at,
        )
        for row in alert_rows[:40]
    ]

    return MonitoringOut(
        generated_at=now,
        total=totals["total"], online=totals["online"], offline=totals["offline"], unknown=totals["unknown"],
        stale_7d=totals["stale"], without_agent=totals["no_agent"],
        agent_available_version=available, agent_outdated=totals["outdated"],
        win_not_activated=totals["win"], office_not_activated=totals["office"],
        kms_unreachable=totals["kms"], disks_critical=totals["disk"],
        tasks_running=tasks_running, tasks_failed_24h=tasks_failed,
        alerts_24h=len(alert_rows), alerts=alerts, buildings=building_out,
    )
