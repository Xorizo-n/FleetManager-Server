from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from config import settings

from models.playbook import PlaybookSchedule
from schemas.playbook import PlaybookScheduleOut
from services.playbook_meta import playbook_meta


def schedule_group_ids(schedule: PlaybookSchedule) -> list[str]:
    """Target groups of the schedule; older rows keep a single group in host_group_id."""
    group_ids = [str(group_id) for group_id in (schedule.host_group_ids or [])]
    if schedule.host_group_id:
        group_ids.append(str(schedule.host_group_id))
    return list(dict.fromkeys(group_ids))


def schedule_tag_ids(schedule: PlaybookSchedule) -> list[str]:
    return list(dict.fromkeys(str(tag_id) for tag_id in (schedule.host_tag_ids or [])))


def next_run_at(cron_expression: str, now: datetime | None = None) -> datetime | None:
    """Следующий запуск; cron — местное время (settings.schedule_timezone), как и в
    services.ansible_runner.schedule_is_due."""
    from croniter import croniter

    local_now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(settings.schedule_timezone))
    try:
        return croniter(cron_expression, local_now).get_next(datetime)
    except (ValueError, KeyError):
        return None


def schedule_out(schedule: PlaybookSchedule, now: datetime | None = None) -> PlaybookScheduleOut:
    out = PlaybookScheduleOut.model_validate(schedule)
    out.host_group_ids = schedule_group_ids(schedule)
    out.host_tag_ids = schedule_tag_ids(schedule)
    out.next_run_at = next_run_at(schedule.cron_expression, now) if schedule.enabled else None
    meta = playbook_meta(schedule.repo.local_path if schedule.repo else None, schedule.playbook_name)
    out.playbook_title, out.playbook_description = meta.title, meta.description
    owner = schedule.owner
    if owner is not None:
        out.owner_name = owner.display_name or owner.username
        out.owner_domain = owner.auth_source == "ldap"
    return out
