from __future__ import annotations

import socket
import uuid
from datetime import datetime, timezone

from celery_app import celery_app
from config import settings
from database import SessionLocal
from models.host import Host, HostStatus, HostStatusHistory
from models.task import TaskRun, TaskStatus
from services.ansible_runner import build_full_inventory, run_ansible
from services.host_diagnostic_utils import format_stage, inventory_host_key, sanitize_detail
from services.host_target import normalize_host_address, resolve_host_target


def _append_log(db, task: TaskRun, message: str, *, stage: str, ok: bool | None = None) -> None:
    line = format_stage(stage, sanitize_detail(message), ok=ok)
    task.log_output = f"{task.log_output}\n{line}" if task.log_output else line
    db.commit()


def _record_host_status(db, host: Host, status: HostStatus) -> None:
    now = datetime.now(timezone.utc)
    host.status = status
    host.last_checked_at = now
    db.add(HostStatusHistory(host_id=host.id, status=status, recorded_at=now))


def _finish_task(db, task: TaskRun, status: TaskStatus) -> None:
    task.status = status
    task.finished_at = datetime.now(timezone.utc)
    db.commit()


def _ssh_port(host: Host) -> int:
    return host.ssh_port or settings.ansible_ssh_port


def _dns_stage(hostname: str | None, target: str) -> tuple[bool | None, str]:
    """DNS stage of the diagnostic: (ok, message) for the log.

    The connection goes to the IP address the agent reports, so a hostname the
    server's resolver does not know (a PC from another domain's zone, e.g.
    at.urfu.ru while the containers search rtf.ustu) is only informational.
    The lookup error is raised only when the hostname itself is the target.
    """
    name = normalize_host_address(hostname)
    if name is None:
        return None, "skipped: no hostname, target is an IP address"
    try:
        addresses = socket.getaddrinfo(name, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        if name == target:
            raise
        return None, f"{name} does not resolve ({exc}); connecting by IP {target}"
    resolved = sorted({item[4][0] for item in addresses if item[4]})
    return True, f"resolved {len(resolved)} address(es): {', '.join(resolved)}"


@celery_app.task(name="services.host_diagnostics.run_host_diagnostic")
def run_host_diagnostic(task_run_id: str):
    db = SessionLocal()
    task = None
    host = None
    stage = "initialization"
    try:
        task = db.get(TaskRun, uuid.UUID(task_run_id))
        if task is None:
            return

        task.status = TaskStatus.running
        task.started_at = datetime.now(timezone.utc)
        db.commit()
        _append_log(db, task, "diagnostic started", stage="START")

        host_id = uuid.UUID(task.host_ids[0])
        host = db.get(Host, host_id)
        if host is None:
            raise RuntimeError("host not found")

        stage = "target"
        target = resolve_host_target(host.hostname, host.ip_address)
        _append_log(db, task, f"target selected: {target}", stage=stage, ok=True)

        stage = "dns"
        dns_ok, dns_message = _dns_stage(host.hostname, target)
        _append_log(db, task, dns_message, stage=stage, ok=dns_ok)

        stage = "tcp"
        ssh_port = _ssh_port(host)
        with socket.create_connection((target, ssh_port), timeout=3):
            pass
        _append_log(db, task, f"TCP port {ssh_port} is reachable", stage=stage, ok=True)

        stage = "ansible"
        inventory = build_full_inventory(db, [host.id])
        inventory_host = inventory_host_key(host.id)
        _append_log(db, task, f"starting Ansible SSH check for inventory host {inventory_host}", stage=stage)
        result = run_ansible(
            module="ansible.builtin.raw",
            module_args="echo fleet-diagnostic-ok",
            host_pattern=inventory_host,
            inventory=inventory,
            quiet=True,
        )

        reachable = False
        failure_message = f"runner return code: {result.rc}"
        for event in result.events:
            event_data = event.get("event_data", {})
            if event_data.get("host") != inventory_host:
                continue
            res = event_data.get("res") or {}
            if event.get("event") == "runner_on_ok" and res.get("rc", 1) == 0:
                reachable = True
                stdout = (res.get("stdout") or "").strip()
                _append_log(db, task, f"command completed (rc=0, output={stdout[:120]})", stage="command", ok=True)
                break
            if event.get("event") in ("runner_on_unreachable", "runner_on_failed"):
                failure_message = sanitize_detail(str(res.get("msg") or event.get("event")))

        if not reachable:
            raise RuntimeError(failure_message)

        _record_host_status(db, host, HostStatus.online)
        db.commit()
        _append_log(db, task, "host is reachable", stage="RESULT", ok=True)
        _finish_task(db, task, TaskStatus.success)
    except Exception as exc:  # noqa: BLE001
        if task is not None:
            _append_log(db, task, f"{type(exc).__name__}: {exc}", stage=stage, ok=False)
            if host is not None:
                _record_host_status(db, host, HostStatus.offline)
                db.commit()
            _finish_task(db, task, TaskStatus.failed)
    finally:
        db.close()
