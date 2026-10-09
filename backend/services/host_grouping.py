"""Automatic host groups by computer name, the same scheme AutoDomain uses for OUs.

SU5-D206-TEMP -> building SU5 > floor "SU5 2 этаж" > room "SU5-D206"; the host goes
into the room group. Only names matching settings.host_name_pattern
(BUILDING-ROOM-TYPE, the floor is the first digit of the room number) are grouped.

Groups are created on demand, so the tree grows as PCs register. A room group that
already exists under that name (for example a manually created MR32-411) is reused
and attached to its floor. A host in a manually created group with another name is
left where an administrator put it; hosts in automatic groups follow their name.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from celery_app import celery_app
from config import settings
from database import SessionLocal
from models.host import Host, HostGroup

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HostNameParts:
    building: str
    room: str
    floor: str

    @property
    def building_group(self) -> str:
        return self.building

    @property
    def floor_group(self) -> str:
        return f"{self.building} {self.floor} этаж"

    @property
    def room_group(self) -> str:
        return f"{self.building}-{self.room}"


@lru_cache(maxsize=4)
def _name_regex(pattern: str) -> re.Pattern:
    # AutoDomain (.NET) writes named groups as (?<Name>...), Python needs (?P<Name>...).
    return re.compile(re.sub(r"\(\?<(?=[A-Za-z])", "(?P<", pattern), re.IGNORECASE)


def parse_host_name(hostname: str | None, pattern: str | None = None) -> HostNameParts | None:
    if not hostname:
        return None
    match = _name_regex(pattern or settings.host_name_pattern).match(hostname.strip())
    if not match:
        return None
    parts = match.groupdict()
    if not all(parts.get(key) for key in ("Building", "Room", "Floor")):
        return None
    return HostNameParts(parts["Building"].upper(), parts["Room"].upper(), parts["Floor"])


def should_move(current_name: str | None, current_is_auto: bool, room_group: str) -> bool:
    """Whether the host goes into room_group: ungrouped hosts and hosts in automatic
    groups do; a manual group is kept unless it already is this room's group."""
    if current_name is None:
        return True
    if current_name == room_group:
        return True
    return current_is_auto


def _ensure_group(db: Session, name: str, parent: HostGroup | None, description: str) -> HostGroup:
    group = db.execute(select(HostGroup).where(HostGroup.name == name)).scalar_one_or_none()
    if group is None:
        group = HostGroup(name=name, description=description, parent=parent, is_auto=True)
        db.add(group)
        db.flush()
        logger.info("Created host group %s", name)
    elif parent is not None and group.parent_id is None and group.id != parent.id:
        # Existing group with the room/floor name (e.g. a manual MR32-411): put it into the tree.
        group.parent = parent
        if not group.description:
            group.description = description
    return group


def auto_group_host(db: Session, host: Host) -> HostGroup | None:
    """Puts the host into its room group (creating the tree as needed); returns the
    room group, or None if the name does not match or the host stays where it is.
    Flushes but does not commit."""
    if not settings.host_auto_grouping:
        return None
    parts = parse_host_name(host.hostname)
    if parts is None:
        return None
    current = host.group
    if not should_move(current.name if current else None, bool(current and current.is_auto), parts.room_group):
        return None

    building = _ensure_group(db, parts.building_group, None, f"Корпус {parts.building}")
    floor = _ensure_group(db, parts.floor_group, building, f"{parts.building}, {parts.floor} этаж")
    room = _ensure_group(db, parts.room_group, floor, f"Аудитория {parts.room} ({parts.building}, {parts.floor} этаж)")
    if host.group_id != room.id:
        host.group = room
        logger.info("Host %s moved to group %s", host.hostname, room.name)
    return room


def apply_auto_group(db: Session, host: Host) -> None:
    """auto_group_host with its own commit; never raises into the caller (heartbeat,
    registration). Two PCs of a new room registering at once can race on creating
    the same group — the loser retries once and finds it."""
    for attempt in (1, 2):
        try:
            auto_group_host(db, host)
            db.commit()
            return
        except IntegrityError:
            db.rollback()
            if attempt == 2:
                logger.warning("Automatic grouping of %s failed: group name conflict", host.hostname)
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("Automatic grouping of %s failed", host.hostname)
            return


@celery_app.task(name="services.host_grouping.regroup_hosts")
def regroup_hosts() -> int:
    """Groups every host by name, including hosts added by hand and agents that are
    offline. Returns how many hosts were moved."""
    db = SessionLocal()
    moved = 0
    try:
        for host in db.execute(select(Host)).scalars().all():
            before = host.group_id
            apply_auto_group(db, host)
            if host.group_id != before:
                moved += 1
        return moved
    finally:
        db.close()
