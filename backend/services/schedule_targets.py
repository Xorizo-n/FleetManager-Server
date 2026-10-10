from datetime import datetime, timezone

from models.playbook import PlaybookSchedule
from schemas.playbook import PlaybookScheduleOut


def schedule_group_ids(schedule: PlaybookSchedule) -> list[str]:
    """Target groups of the schedule; older rows keep a single group in host_group_id."""
    group_ids = [str(group_id) for group_id in (schedule.host_group_ids or [])]
    if schedule.host_group_id:
        group_ids.append(str(schedule.host_group_id))
    return list(dict.fromkeys(group_ids))


def next_run_at(cron_expression: str, now: datetime | None = None) -> datetime | None:
    from croniter import croniter

    try:
        return croniter(cron_expression, now or datetime.now(timezone.utc)).get_next(datetime)
    except (ValueError, KeyError):
        return None


def schedule_out(schedule: PlaybookSchedule, now: datetime | None = None) -> PlaybookScheduleOut:
    out = PlaybookScheduleOut.model_validate(schedule)
    out.host_group_ids = schedule_group_ids(schedule)
    out.next_run_at = next_run_at(schedule.cron_expression, now) if schedule.enabled else None
    return out
