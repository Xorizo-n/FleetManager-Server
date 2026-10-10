"""Automatic host groups by computer name, the same scheme AutoDomain uses for OUs.

SU5-D206-TEMP -> building SU5 > floor "2 этаж" > room "SU5-D206"; the host goes
into the room group. Group names are unique within their parent, so every building
has its own "2 этаж". Only names matching settings.host_name_pattern
(BUILDING-ROOM-TYPE, the floor is the first digit of the room number) are grouped.

Groups are created on demand, so the tree grows as PCs register. A top-level group
that already has the room's name (for example a manually created MR32-411) is reused
and moved under its floor. A host in a manually created group with another name is
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
        return f"{self.floor} этаж"

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


def _group_named(db: Session, name: str, parent: HostGroup | None) -> HostGroup | None:
    """The group with this name in exactly this place of the tree (names are unique per parent)."""
    in_parent = HostGroup.parent_id.is_(None) if parent is None else HostGroup.parent_id == parent.id
    return db.execute(select(HostGroup).where(HostGroup.name == name, in_parent)).scalar_one_or_none()


def _ensure_group(db: Session, name: str, parent: HostGroup | None, description: str, *, adopt: bool = False) -> HostGroup:
    group = _group_named(db, name, parent)
    if group is None and adopt and parent is not None:
        # A top-level group already named like the room (e.g. a manual MR32-411): move it into the tree.
        group = _group_named(db, name, None)
        if group is not None:
            group.parent = parent
            if not group.description:
                group.description = description
    if group is None:
        group = HostGroup(name=name, description=description, parent=parent, is_auto=True)
        db.add(group)
        db.flush()
        logger.info("Created host group %s", name)
    return group


def find_group_by_name(db: Session, name: str) -> HostGroup | None:
    """Group for a name typed by a user (assign by name, CSV import): the top-level group
    with that name, or the only group with it; None if absent or ambiguous ("2 этаж")."""
    groups = db.execute(select(HostGroup).where(HostGroup.name == name)).scalars().all()
    top_level = [group for group in groups if group.parent_id is None]
    if top_level:
        return top_level[0]
    return groups[0] if len(groups) == 1 else None


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
    room = _ensure_group(db, parts.room_group, floor, f"Аудитория {parts.room} ({parts.building}, {parts.floor} этаж)", adopt=True)
    if host.group_id != room.id:
        if not keeps_ssh_access(host.credential_id, group_credential(current), group_credential(room)):
            # ПК подключается учёткой своей группы; перенос сменил бы её без проверки входа
            logger.warning("Host %s stays in %s: moving it to %s would change its SSH credential", host.hostname, current.name, room.name)
            return None
        host.group = room
        logger.info("Host %s moved to group %s", host.hostname, room.name)
    return room


def group_credential(group: HostGroup | None):
    """Id of the credential the group gives its hosts: its own or the nearest parent's."""
    seen: set = set()
    while group is not None and group.id not in seen:
        seen.add(group.id)
        if group.credential_id:
            return group.credential_id
        group = group.parent
    return None


def keeps_ssh_access(own_credential_id, current_group_credential, new_group_credential) -> bool:
    """An automatic move must not change a working SSH credential: hosts with their own
    credential (every agent) are unaffected, hosts without any access cannot lose it."""
    if own_credential_id is not None or current_group_credential is None:
        return True
    return current_group_credential == new_group_credential


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
