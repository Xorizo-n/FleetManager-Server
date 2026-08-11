from datetime import datetime, timezone

from models.host import Host
from models.software import SoftwareItem, SoftwareHistory, InstallMethod, SoftwareStatus, ChangeType


def sync_host_software(db, host: Host, discovered: dict[str, tuple[str, InstallMethod]]) -> None:
    """Сверяет обнаруженный на хосте набор ПО с текущим состоянием в БД и пишет историю изменений."""
    existing_items = {
        item.name: item
        for item in db.query(SoftwareItem).filter(
            SoftwareItem.host_id == host.id, SoftwareItem.status == SoftwareStatus.installed
        ).all()
    }

    now = datetime.now(timezone.utc)

    for name, (version, method) in discovered.items():
        existing = existing_items.pop(name, None)
        if existing is None:
            db.add(SoftwareItem(host_id=host.id, name=name, version=version, install_method=method, status=SoftwareStatus.installed, detected_at=now))
            db.add(SoftwareHistory(host_id=host.id, name=name, old_version=None, new_version=version, change_type=ChangeType.added))
        elif existing.version != version:
            db.add(SoftwareHistory(host_id=host.id, name=name, old_version=existing.version, new_version=version, change_type=ChangeType.updated))
            existing.version = version
            existing.detected_at = now

    for name, item in existing_items.items():
        item.status = SoftwareStatus.removed
        db.add(SoftwareHistory(host_id=host.id, name=name, old_version=item.version, new_version=None, change_type=ChangeType.removed))

    host.last_checked_at = now
    db.commit()
