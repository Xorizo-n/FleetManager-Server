import os
import time
from datetime import datetime, timedelta, timezone

import psutil
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user
from models.host import Host, HostStatus, HostStatusHistory
from models.software import SoftwareItem, SoftwareHistory, SoftwareStatus
from models.task import TaskRun
from models.user import User
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
