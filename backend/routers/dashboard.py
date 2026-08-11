from datetime import datetime, timedelta, timezone

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
    since = datetime.now(timezone.utc) - timedelta(days=7)
    rows = db.execute(select(TaskRun.created_at, TaskRun.status).where(TaskRun.created_at >= since)).all()

    buckets: dict[str, dict[str, int]] = {}
    for created_at, status_value in rows:
        day_key = created_at.strftime("%Y-%m-%d")
        buckets.setdefault(day_key, {"success": 0, "failed": 0})
        if status_value.value in ("success", "failed"):
            buckets[day_key][status_value.value] += 1

    return [WeeklyRunStats(day=k, success=v["success"], failed=v["failed"]) for k, v in sorted(buckets.items())]
