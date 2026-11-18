from datetime import datetime, timezone
import logging

import redis
from redis.exceptions import LockNotOwnedError

from celery_app import celery_app
from config import settings
from database import SessionLocal
from models.host import Host, HostStatus, HostStatusHistory
from services.ansible_runner import build_full_inventory, run_ansible
from services.waiting_tasks import release_waiting_tasks

logger = logging.getLogger(__name__)
CHECK_TIMEOUT = 240
LOCK_TIMEOUT = 600


@celery_app.task(name="services.host_health.ping_hosts")
def ping_hosts():
    lock = redis.Redis.from_url(settings.celery_broker_url).lock(
        "fleet-manager:host-health", timeout=LOCK_TIMEOUT, blocking_timeout=0,
    )
    if not lock.acquire(blocking=False):
        logger.info("Host health check already running; skipping duplicate")
        return
    try:
        _ping_hosts()
    finally:
        try:
            lock.release()
        except LockNotOwnedError:
            logger.warning("Host health lock expired before check finished")


def _ping_hosts():
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
        result = run_ansible(
            module="ansible.builtin.raw",
            module_args="echo fleet-ping-ok",
            host_pattern="all",
            inventory=inventory,
            quiet=True,
            timeout=CHECK_TIMEOUT,
            settings={"idle_timeout": 30},
            envvars={"ANSIBLE_SSH_ARGS": (
                "-o ControlMaster=no -o ControlPersist=no -o ConnectTimeout=5 "
                "-o ServerAliveInterval=5 -o ServerAliveCountMax=2"
            )},
        )
        # Unreachable hosts normally produce "failed" with complete statistics.
        # Timeouts and interrupted runs must not mark untested hosts offline.
        if result.status not in ("successful", "failed") or not result.stats:
            logger.warning("Host health check incomplete (%s, rc=%s); discarding partial snapshot",
                           result.status, result.rc)
            return

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

        # У ПК без агента heartbeat нет: ожидающие задачи запускает проверка по SSH
        for host in hosts:
            if str(host.id) in reachable_hosts:
                release_waiting_tasks(db, host.id, reason="проверка по SSH")
    finally:
        db.close()
