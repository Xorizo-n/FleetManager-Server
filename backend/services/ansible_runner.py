import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

from celery_app import celery_app
from config import settings
from database import SessionLocal
from models.credential import CredentialType
from models.host import Host
from models.playbook import PlaybookRepo, PlaybookSchedule
from models.task import TaskRun, TaskStatus, TaskType
from services.crypto import decrypt_secret
from services.inventory_generator import build_inventory_dict, resolve_host_group_members


def _resolve_credential_vars(host: Host) -> dict:
    credential = host.credential or (host.group.credential if host.group_id and host.group else None)
    if credential is None:
        return {}

    secret = decrypt_secret(credential.secret_encrypted)

    if credential.type == CredentialType.ssh_key:
        os.makedirs(settings.ansible_private_key_dir, exist_ok=True)
        key_path = os.path.join(settings.ansible_private_key_dir, f"{credential.id}.pem")
        if not os.path.exists(key_path):
            with open(key_path, "w") as f:
                f.write(secret)
            os.chmod(key_path, 0o600)
        return {"ansible_user": credential.login, "ansible_ssh_private_key_file": key_path}

    # password / token credentials both map to ansible_password (e.g. WinRM auth)
    return {"ansible_user": credential.login, "ansible_password": secret}


def build_full_inventory(db, host_ids: list[uuid.UUID] | None) -> dict:
    """Inventory для реального запуска ansible-runner, с подставленными (расшифрованными) credentials."""
    inventory = build_inventory_dict(db, host_ids)
    query = db.query(Host)
    if host_ids:
        query = query.filter(Host.id.in_(host_ids))
    hosts = query.all()

    for host in hosts:
        group_name = host.group.name if host.group_id and host.group else "ungrouped"
        host_vars = inventory["all"]["children"][group_name]["hosts"][str(host.id)]
        host_vars.pop("_fleet_host_id", None)
        host_vars.pop("_fleet_credential_id", None)
        host_vars.update(_resolve_credential_vars(host))

    return inventory


def playbook_matched_hosts(result, expected_hosts: set[str], observed_hosts: set[str] | None = None) -> bool:
    """Return false when Ansible exits cleanly without matching any target host."""
    if getattr(result, "rc", 1) != 0:
        return False
    observed = observed_hosts if observed_hosts is not None else set(getattr(result, "stats", None) or {})
    return not expected_hosts or bool(observed.intersection(expected_hosts))


@celery_app.task(name="services.ansible_runner.run_playbook_task", bind=True)
def run_playbook_task(self, task_run_id: str):
    import ansible_runner

    db = SessionLocal()
    try:
        task_run = db.get(TaskRun, uuid.UUID(task_run_id))
        if task_run is None:
            return

        task_run.status = TaskStatus.running
        task_run.started_at = datetime.now(timezone.utc)
        task_run.celery_task_id = self.request.id
        db.commit()

        repo = db.get(PlaybookRepo, task_run.repo_id) if task_run.repo_id else None
        if repo is None:
            raise RuntimeError("Не указан репозиторий плейбуков")

        inventory = build_full_inventory(db, [uuid.UUID(h) for h in task_run.host_ids])

        log_lines: list[str] = []
        observed_hosts: set[str] = set()

        def event_handler(event):
            host = (event.get("event_data") or {}).get("host")
            if host:
                observed_hosts.add(host)
            stdout = event.get("stdout")
            if stdout:
                log_lines.append(stdout)
                task_run.log_output = "\n".join(log_lines)
                db.commit()

        result = ansible_runner.run(
            private_data_dir=tempfile.mkdtemp(prefix="runner-"),
            playbook=task_run.playbook_name,
            project_dir=repo.local_path,
            inventory=inventory,
            extravars=task_run.extra_vars or {},
            event_handler=event_handler,
            quiet=True,
        )

        expected_hosts = {str(host_id) for host_id in task_run.host_ids}
        if result.rc != 0:
            task_run.status = TaskStatus.failed
        elif not playbook_matched_hosts(result, expected_hosts, observed_hosts):
            task_run.status = TaskStatus.failed
            task_run.log_output = (task_run.log_output or "") + "\n[ERROR] Playbook matched no hosts."
        else:
            task_run.status = TaskStatus.success
        task_run.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        task_run = db.get(TaskRun, uuid.UUID(task_run_id))
        if task_run:
            task_run.status = TaskStatus.failed
            task_run.log_output = (task_run.log_output or "") + f"\n[ERROR] {exc}"
            task_run.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


@celery_app.task(name="services.ansible_runner.dispatch_scheduled_playbooks")
def dispatch_scheduled_playbooks():
    from croniter import croniter

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        schedules = db.query(PlaybookSchedule).filter(PlaybookSchedule.enabled.is_(True)).all()

        for schedule in schedules:
            cron = croniter(schedule.cron_expression, now - timedelta(minutes=1))
            next_fire = cron.get_next(datetime)
            if next_fire > now:
                continue  # ничего не должно было сработать за последнюю минуту

            host_ids = list(schedule.host_ids or [])
            if schedule.host_group_id:
                host_ids += [str(h.id) for h in resolve_host_group_members(db, schedule.host_group_id)]

            task_run = TaskRun(
                task_type=TaskType.playbook,
                repo_id=schedule.repo_id,
                playbook_name=schedule.playbook_name,
                host_ids=host_ids,
                extra_vars=schedule.extra_vars,
                status=TaskStatus.queued,
            )
            db.add(task_run)
            db.commit()
            db.refresh(task_run)
            run_playbook_task.delay(str(task_run.id))
    finally:
        db.close()
