"""Request a normal Windows restart through the existing SSH channel."""
import uuid
from datetime import datetime, timezone

from celery_app import celery_app
from database import SessionLocal
from models.host import Host, HostStatus
from models.task import TaskRun, TaskStatus
from services.ansible_runner import build_full_inventory, run_raw_command
from services.host_parallel import HostOutcome, append_task_log, host_label, run_for_hosts
from services.power_state import updates_installing

# No /f: don't ask Windows to forcibly close applications. A restart may close
# SSH before the marker arrives, so an interrupted response is always uncertain.
RESTART_COMMAND = r"""
$ErrorActionPreference = 'Stop'
& shutdown.exe /r /t 0
if ($LASTEXITCODE -ne 0) { throw "shutdown.exe returned $LASTEXITCODE" }
Write-Output 'FLEET_RESTART_ACCEPTED'
"""


def restart_host(db, task_id, inventory, host):
    label = host_label(host)
    if host.status != HostStatus.online:
        append_task_log(db, task_id, f"[{label}] не в сети: команда не отправлена")
        return HostOutcome.unreachable
    if updates_installing(host.power_state):
        append_task_log(db, task_id, f"[{label}] устанавливаются обновления Windows: команда не отправлена")
        return HostOutcome.failed
    try:
        output = run_raw_command(inventory, str(host.id), RESTART_COMMAND, timeout=60)
    except Exception:
        # Once the command is sent a dropped SSH connection is not proof of failure.
        append_task_log(db, task_id, f"[{label}] не удалось подтвердить отправку команды: ПК мог начать перезагрузку; проверьте его состояние перед повтором")
        return HostOutcome.failed
    if "FLEET_RESTART_ACCEPTED" not in output:
        append_task_log(db, task_id, f"[{label}] ответ не подтверждает перезагрузку; проверьте состояние перед повтором")
        return HostOutcome.failed
    append_task_log(db, task_id, f"[{label}] Windows приняла команду перезагрузки; завершение перезагрузки не проверялось")
    return HostOutcome.ok


@celery_app.task(name="services.host_restart.run_host_restart")
def run_host_restart(task_run_id):
    db = SessionLocal()
    try:
        task = db.get(TaskRun, uuid.UUID(task_run_id))
        if task is None: return
        task.status = TaskStatus.running
        task.started_at = datetime.now(timezone.utc)
        db.commit()
        host_ids = [uuid.UUID(item) for item in task.host_ids]
        inventory = build_full_inventory(db, host_ids)
        failed = run_for_hosts(task.id, host_ids, lambda host_db, host: restart_host(host_db, task.id, inventory, host),
                               missing_outcome=HostOutcome.failed)
        task.status = TaskStatus.failed if failed else TaskStatus.success
        task.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        task = db.get(TaskRun, uuid.UUID(task_run_id))
        if task is not None:
            append_task_log(db, task.id, f"[ERROR] {exc}")
            task.status = TaskStatus.failed
            task.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
