import tempfile
from datetime import datetime, timezone

from celery_app import celery_app
from database import SessionLocal
from models.host import Host, HostStatus, HostStatusHistory
from services.ansible_runner import build_full_inventory


@celery_app.task(name="services.host_health.ping_hosts")
def ping_hosts():
    import ansible_runner

    db = SessionLocal()
    try:
        hosts = db.query(Host).all()
        if not hosts:
            return

        host_ids = [h.id for h in hosts]
        inventory = build_full_inventory(db, host_ids)

        # Используем raw + echo вместо win_ping/WinRM, чтобы не тянуть отдельные Ansible
        # коллекции — раз ansible_connection везде ssh (см. build_full_inventory), достаточно
        # проверить, что SSH-сессия вообще устанавливается и выполняет команду.
        result = ansible_runner.run(
            private_data_dir=tempfile.mkdtemp(prefix="ping-"),
            module="ansible.builtin.raw",
            module_args="echo fleet-ping-ok",
            host_pattern="all",
            inventory=inventory,
            quiet=True,
        )

        reachable_hosts: set[str] = set()
        for event in result.events:
            if event.get("event") != "runner_on_ok":
                continue
            event_data = event.get("event_data", {})
            host = event_data.get("host")
            res = event_data.get("res") or {}
            if host and res.get("rc", 1) == 0:
                reachable_hosts.add(host)

        now = datetime.now(timezone.utc)
        for host in hosts:
            new_status = HostStatus.online if str(host.id) in reachable_hosts else HostStatus.offline
            host.status = new_status
            host.last_checked_at = now
            db.add(HostStatusHistory(host_id=host.id, status=new_status, recorded_at=now))

        db.commit()
    finally:
        db.close()
