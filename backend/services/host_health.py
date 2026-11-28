from datetime import datetime, timezone
import logging

import redis
from redis.exceptions import LockNotOwnedError
from sqlalchemy import or_, update

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
        started_at = datetime.now(timezone.utc)

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
        by_key = {str(host_id): host_id for host_id in host_ids}
        outcomes = {}
        for event in result.events:
            event_data = event.get("event_data") or {}
            host_id = by_key.get(event_data.get("host"))
            if host_id is None:
                continue
            kind = event.get("event")
            if kind == "runner_on_ok" and (event_data.get("res") or {}).get("rc") == 0:
                outcomes[host_id] = HostStatus.online
            elif kind in ("runner_on_failed", "runner_on_unreachable"):
                outcomes[host_id] = HostStatus.offline

        if result.status not in ("successful", "failed") or not result.stats:
            logger.warning("Host health check incomplete (%s, rc=%s); got results for %s/%s hosts",
                           result.status, result.rc, len(outcomes), len(host_ids))
        if not outcomes:
            return

        now = datetime.now(timezone.utc)
        reachable_hosts = []
        for status in (HostStatus.online, HostStatus.offline):
            checked = [host_id for host_id, outcome in outcomes.items() if outcome == status]
            if not checked:
                continue
            # A heartbeat or on-demand diagnostic during the batch takes precedence.
            saved = db.execute(
                update(Host)
                .where(Host.id.in_(checked), or_(Host.last_checked_at.is_(None), Host.last_checked_at <= started_at))
                .values(status=status, last_checked_at=now)
                .returning(Host.id)
                .execution_options(synchronize_session=False)
            ).scalars().all()
            db.add_all([HostStatusHistory(host_id=host_id, status=status, recorded_at=now) for host_id in saved])
            if status == HostStatus.online:
                reachable_hosts = saved

        db.commit()

        # У ПК без агента heartbeat нет: ожидающие задачи запускает проверка по SSH
        for host_id in reachable_hosts:
            release_waiting_tasks(db, host_id, reason="проверка по SSH")
    finally:
        db.close()
