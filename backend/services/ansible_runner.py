import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from types import SimpleNamespace

from celery_app import celery_app
from config import settings
from database import SessionLocal
from models.credential import CredentialType
from models.host import Host
from models.playbook import PlaybookRepo, PlaybookSchedule
from models.task import TaskRun, TaskStatus, TaskType
from services.crypto import decrypt_secret
from services.ssh_health import host_keys
from services.inventory_generator import build_inventory_dict, host_group_credential, resolve_target_host_ids
from services.schedule_targets import schedule_group_ids
from services import run_as


def run_ansible(**kwargs):
    """Run Ansible and materialize its lazy result before cleanup.

    ansible-runner exposes ``events`` as a lazy iterator backed by files below
    ``private_data_dir``. Materialize events and stats while that directory is
    still alive, then remove it so completed tasks cannot accumulate artifacts.
    The inventory separately disables OpenSSH control persistence.
    """
    import ansible_runner

    with tempfile.TemporaryDirectory(prefix="ansible-") as private_data_dir:
        result = ansible_runner.run(private_data_dir=private_data_dir, **kwargs)
        events = list(result.events)
        stats = result.stats
        return SimpleNamespace(rc=result.rc, status=result.status, stats=stats, events=events)


def run_raw_command(inventory: dict, inventory_host: str, command: str, *, timeout: int | None = None) -> str:
    """Выполняет команду через ansible.builtin.raw на одном хосте и возвращает stdout.

    Хосты Windows подключаются по SSH с ansible_shell_type=powershell (см.
    inventory_generator), поэтому raw — единственный доступный способ выполнения:
    отдельные Ansible-коллекции (ansible.windows) в образ не устанавливаются.
    """
    kwargs = {
        "module": "ansible.builtin.raw",
        "module_args": command,
        "host_pattern": inventory_host,
        "inventory": inventory,
        "quiet": True,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    result = run_ansible(**kwargs)

    output_parts: list[str] = []
    failure_msg = None
    for event in result.events:
        event_data = event.get("event_data", {})
        if event_data.get("host") != inventory_host:
            continue

        res = event_data.get("res") or {}
        if event.get("event") in ("runner_on_unreachable", "runner_on_failed"):
            failure_msg = res.get("msg") or res.get("stdout") or event.get("event")
        stdout = res.get("stdout")
        if stdout:
            output_parts.append(stdout)

    if failure_msg is not None:
        raise RuntimeError(f"Ansible: {failure_msg}")

    return "\n".join(output_parts)


def _resolve_credential_vars(host: Host) -> dict:
    return credential_vars(host.credential or host_group_credential(host))


def credential_vars(credential) -> dict:
    """Ansible connection vars for a credential (the key is written to a file once)."""
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


def known_host_args(host: Host) -> str:
    """Проверка ключа хоста по ключам, которые прислал его агент, и по id хоста, а не по IP.

    Общий known_hosts Ansible привязан к IP: после подготовки ПК из образа (AutoDomain генерирует
    новые ключи хоста) или когда DHCP отдаёт адрес другому ПК, SSH отказывал с «REMOTE HOST
    IDENTIFICATION HAS CHANGED». Ключи приходят от агента по его токену, поэтому им можно
    доверять строже, чем первому подключению. Нет ключей (старый агент) — как раньше."""
    keys = host_keys(host.ssh_state)
    if not keys:
        return ""
    folder = os.path.join(settings.ansible_private_key_dir, "known_hosts")
    os.makedirs(folder, mode=0o700, exist_ok=True)
    path = os.path.join(folder, str(host.id))
    content = "".join(f"{host.id} {key}\n" for key in keys)
    try:
        with open(path, encoding="utf-8") as f:
            current = f.read()
    except OSError:
        current = None
    if current != content:
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    return f" -o HostKeyAlias={host.id} -o UserKnownHostsFile={path} -o StrictHostKeyChecking=yes"


def build_full_inventory(db, host_ids: list[uuid.UUID] | None, login_overrides: dict[str, str] | None = None) -> dict:
    """Inventory для реального запуска ansible-runner, с подставленными (расшифрованными) credentials.

    login_overrides — {host_id: логин}: вход тем же SSH-ключом, но под другой учёткой (services/run_as.py)."""
    inventory = build_inventory_dict(db, host_ids)
    query = db.query(Host)
    if host_ids:
        query = query.filter(Host.id.in_(host_ids))
    hosts = query.all()

    for host in hosts:
        # Win_Hosts holds every selected host and shares the vars dict with its own
        # group, so the credential lands everywhere without knowing the group's name.
        host_vars = inventory["all"]["children"]["Win_Hosts"]["hosts"][str(host.id)]
        host_vars.pop("_fleet_host_id", None)
        host_vars.pop("_fleet_credential_id", None)
        host_vars.update(_resolve_credential_vars(host))
        host_vars["ansible_ssh_common_args"] = (host_vars.get("ansible_ssh_common_args", "") + known_host_args(host)).strip()
        if login_overrides and str(host.id) in login_overrides and host_vars.get("ansible_ssh_private_key_file"):
            host_vars["ansible_user"] = login_overrides[str(host.id)]

    return inventory


def playbook_matched_hosts(result, expected_hosts: set[str], observed_hosts: set[str] | None = None) -> bool:
    """Return false when Ansible exits cleanly without matching any target host."""
    if getattr(result, "rc", 1) != 0:
        return False
    observed = observed_hosts if observed_hosts is not None else set(getattr(result, "stats", None) or {})
    return not expected_hosts or bool(observed.intersection(expected_hosts))


def host_outcomes(result, expected_hosts: set[str], *, trusted: bool, fallback: TaskStatus) -> dict[str, str]:
    """Итог по каждому ПК из PLAY RECAP: failed — ошибка или недоступен, success — прошёл.

    Хост, которого нет в recap, плейбук не тронул (не подошёл ни одному play) — это
    ошибка. Если recap не напечатан (прогон оборвался), верить статистике нельзя:
    всем ПК — итог задачи целиком.
    """
    stats = getattr(result, "stats", None) or {}
    processed = set(stats.get("processed") or {})
    if not trusted or not processed:
        state = "success" if fallback == TaskStatus.success else "failed"
        return {host: state for host in expected_hosts}
    failed = set(stats.get("failures") or {}) | set(stats.get("dark") or {})
    return {host: "failed" if host in failed or host not in processed else "success" for host in expected_hosts}


@celery_app.task(name="services.ansible_runner.run_playbook_task", bind=True)
def run_playbook_task(self, task_run_id: str):
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

        # От чьего имени: инициатор (у расписания — владелец), где он администратор ПК
        plan = run_as.plan(db, [str(h) for h in task_run.host_ids], task_run.run_as_user_id or task_run.created_by)
        task_run.run_as = plan.summary()
        names = {str(h.id): h.hostname or str(h.id) for h in db.query(Host).filter(Host.id.in_(task_run.host_ids))}
        inventory = build_full_inventory(db, [uuid.UUID(h) for h in task_run.host_ids], plan.overrides())

        log_lines: list[str] = run_as.log_lines(plan, names) + [""]
        task_run.log_output = "\n".join(log_lines)
        db.commit()
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

        result = run_ansible(
            playbook=task_run.playbook_name,
            project_dir=repo.local_path,
            inventory=inventory,
            extravars=task_run.extra_vars or {},
            event_handler=event_handler,
            quiet=True,
        )

        expected_hosts = {str(host_id) for host_id in task_run.host_ids}
        # ansible-runner может вернуть rc=0, даже если процесс оборвался раньше
        # времени (например, контроллер упёрся в лимит ресурсов и
        # ansible-playbook был убит на полпути) - тогда result.status не
        # 'successful'. Одного rc для этого недостаточно, из-за чего статус
        # "success" мог выставляться на прогон, который по факту ничего не
        # доделал (см. деплой образов R-411 12-14.09).
        #
        # Проверяем по тексту "PLAY RECAP" в самом логе, а не по наличию
        # структурного события playbook_on_stats в result.events - на очень
        # длинных прогонах (десятки минут, много событий) это событие иногда
        # не попадает в постфактум прочитанный result.events из-за гонки при
        # финализации артефактов ansible-runner, хотя recap реально был
        # напечатан и прогон реально закончился штатно (проверено вживую:
        # файлы на дисках хостов были на месте при таком расхождении).
        has_final_recap = "PLAY RECAP" in (task_run.log_output or "")
        if result.rc != 0:
            task_run.status = TaskStatus.failed
        elif result.status != "successful":
            task_run.status = TaskStatus.failed
            task_run.log_output = (task_run.log_output or "") + (
                f"\n[ERROR] ansible-runner сообщил статус '{result.status}' при rc=0 - "
                "похоже, прогон оборвался раньше времени. Результат недостоверен."
            )
        elif not has_final_recap:
            task_run.status = TaskStatus.failed
            task_run.log_output = (task_run.log_output or "") + (
                "\n[ERROR] В логе не найден финальный PLAY RECAP - похоже, процесс "
                "оборвался раньше времени, не все плеи/хосты обработаны. "
                "Результат недостоверен, нужен повторный прогон."
            )
        elif not playbook_matched_hosts(result, expected_hosts, observed_hosts):
            task_run.status = TaskStatus.failed
            task_run.log_output = (task_run.log_output or "") + "\n[ERROR] Playbook matched no hosts."
        else:
            task_run.status = TaskStatus.success
        task_run.host_states = host_outcomes(result, expected_hosts, trusted=has_final_recap, fallback=task_run.status)
        task_run.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        task_run = db.get(TaskRun, uuid.UUID(task_run_id))
        if task_run:
            task_run.status = TaskStatus.failed
            task_run.host_states = {str(h): "failed" for h in task_run.host_ids}
            task_run.log_output = (task_run.log_output or "") + f"\n[ERROR] {exc}"
            task_run.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def schedule_is_due(cron_expression: str, now: datetime) -> bool:
    """Должно ли расписание сработать за последнюю минуту.

    Cron считается по местному времени (settings.schedule_timezone): «0 9 * * *» —
    это 9:00 по Екатеринбургу, как и показывает интерфейс, а не 9:00 UTC (14:00).
    """
    from croniter import croniter

    local_now = now.astimezone(ZoneInfo(settings.schedule_timezone))
    next_fire = croniter(cron_expression, local_now - timedelta(minutes=1)).get_next(datetime)
    return next_fire <= local_now


@celery_app.task(name="services.ansible_runner.dispatch_scheduled_playbooks")
def dispatch_scheduled_playbooks():
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        schedules = db.query(PlaybookSchedule).filter(PlaybookSchedule.enabled.is_(True)).all()

        for schedule in schedules:
            if not schedule_is_due(schedule.cron_expression, now):
                continue  # ничего не должно было сработать за последнюю минуту

            host_ids = resolve_target_host_ids(db, schedule.host_ids or [], schedule_group_ids(schedule))

            task_run = TaskRun(
                task_type=TaskType.playbook,
                repo_id=schedule.repo_id,
                playbook_name=schedule.playbook_name,
                host_ids=host_ids,
                extra_vars=schedule.extra_vars,
                status=TaskStatus.queued,
                run_as_user_id=schedule.owner_id,
            )
            db.add(task_run)
            db.commit()
            db.refresh(task_run)
            run_playbook_task.delay(str(task_run.id))
    finally:
        db.close()
