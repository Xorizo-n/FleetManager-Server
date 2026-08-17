"""Проверка версии и удалённое обновление FleetManager Agent на хостах.

Обе операции идут по тому же каналу, что и остальная автоматизация хостов:
ansible.builtin.raw + PowerShell по SSH (порт 5022, ключ из Key Store).
Отдельных Ansible-коллекций для Windows в образе нет, поэтому сложные скрипты
передаются как -EncodedCommand — так удалённый shell не портит кавычки и пути.

Обновление намеренно устроено как «хост скачивает установщик сам»:

* сервер не передаёт на хост никаких секретов — хост авторизуется своим же
  agent-токеном из `C:\\ProgramData\\FleetManagerAgent\\agent.json`;
* адрес сервера берётся оттуда же, поэтому работает при любом способе публикации
  backend (прямой порт, реверс-прокси, разные DNS-имена);
* установщик отдаёт `GET /api/agent/installer` (см. routers/agent.py).
"""

import base64
import json
import socket
import time
import uuid
from datetime import datetime, timezone

from celery_app import celery_app
from config import settings
from database import SessionLocal
from models.host import Host
from models.task import TaskRun, TaskStatus
from services.agent_version import (
    AGENT_DISPLAY_NAME,
    INSTALLER_FILENAME,
    STATUS_OUTDATED,
    available_agent_version,
    normalize_version,
    version_status,
)
from services.ansible_runner import build_full_inventory, run_raw_command
from services.host_target import resolve_host_target

# Таймауты (сек) на выполнение шага через ansible-runner.
PROBE_TIMEOUT = 120
UPDATE_TIMEOUT = 1800

# Быстрая проверка TCP-доступности перед SSH: инвентарь не задаёт ConnectTimeout
# для ansible_ssh_common_args, поэтому недоступный хост иначе висит на таймауте
# всей SSH-сессии (до PROBE_TIMEOUT/UPDATE_TIMEOUT) вместо мгновенного отказа.
TCP_CHECK_TIMEOUT = 5

# Если SSH-сессия оборвалась во время установки, версию перепроверяем новой
# сессией: установка на хосте при этом обычно доходит до конца.
RECHECK_ATTEMPTS = 6
RECHECK_DELAY = 30

UNINSTALL_KEYS = (
    r"HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
    r"HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
)

# Читает версию из записи удаления, которую создаёт Inno Setup, и состояние службы.
PROBE_SCRIPT = f"""
$ErrorActionPreference = 'SilentlyContinue'
$entry = Get-ItemProperty '{UNINSTALL_KEYS[0]}','{UNINSTALL_KEYS[1]}' |
    Where-Object {{ $_.DisplayName -eq '{AGENT_DISPLAY_NAME}' }} |
    Select-Object -First 1
$service = Get-Service -Name FleetManagerAgent
[pscustomobject]@{{
    version = [string]$entry.DisplayVersion
    install_location = [string]$entry.InstallLocation
    service_status = [string]$service.Status
}} | ConvertTo-Json -Compress
"""

# Скачивает установщик с сервера агентским токеном самого хоста и ставит его
# поверх текущей установки. Инсталлятор сохраняет agent.json (режим обновления),
# поэтому повторная регистрация и enrollment-токен не нужны.
UPDATE_SCRIPT = f"""
$ErrorActionPreference = 'Stop'
$configPath = Join-Path $env:ProgramData 'FleetManagerAgent\\agent.json'
if (-not (Test-Path $configPath)) {{ throw 'agent.json not found: agent is not installed on this host' }}
$config = Get-Content $configPath -Raw | ConvertFrom-Json
if (-not $config.ServerUrl)  {{ throw 'ServerUrl is missing in agent.json' }}
if (-not $config.AgentToken) {{ throw 'AgentToken is missing in agent.json: agent is not registered' }}

$base = $config.ServerUrl.TrimEnd('/')
$dest = Join-Path $env:TEMP '{INSTALLER_FILENAME}'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'
Invoke-WebRequest -Uri "$base/api/agent/installer" -Headers @{{ Authorization = "Bearer $($config.AgentToken)" }} -OutFile $dest -UseBasicParsing -TimeoutSec 900

$process = Start-Process -FilePath $dest -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-' -PassThru
# Deliberately not -Wait: the installer's manifest requires elevation, and
# Start-Process -Wait on a manifest-elevated exe launched over a non-interactive
# SSH session is unreliable — observed on production hosts never returning even
# though the install had already finished and the process itself had exited (no
# child process left, nothing to wait for). Poll instead: HasExited/ExitCode are
# plain non-blocking GetExitCodeProcess() calls, a different code path from the
# blocking wait that hangs, and the registry entry is the authoritative signal
# for "the install actually finished" regardless of the process handle anyway.
$version = $null
$deadline = (Get-Date).AddSeconds(300)
do {{
    Start-Sleep -Seconds 3
    $entry = Get-ItemProperty '{UNINSTALL_KEYS[0]}','{UNINSTALL_KEYS[1]}' -ErrorAction SilentlyContinue |
        Where-Object {{ $_.DisplayName -eq '{AGENT_DISPLAY_NAME}' }} |
        Select-Object -First 1
    $version = [string]$entry.DisplayVersion
}} while (-not $version -and (Get-Date) -lt $deadline)

$exitCode = $null
if ($process.HasExited) {{ $exitCode = $process.ExitCode }}

Remove-Item $dest -Force -ErrorAction SilentlyContinue
$service = Get-Service -Name FleetManagerAgent -ErrorAction SilentlyContinue
[pscustomobject]@{{
    version = $version
    exit_code = $exitCode
    service_status = [string]$service.Status
}} | ConvertTo-Json -Compress
"""


def encode_powershell(script: str) -> str:
    """PowerShell -EncodedCommand: удалённый shell не трогает кавычки и пути."""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return "powershell -NoProfile -NonInteractive -EncodedCommand " + encoded


PROBE_CMD = encode_powershell(PROBE_SCRIPT)
UPDATE_CMD = encode_powershell(UPDATE_SCRIPT)


def parse_probe_output(raw: str) -> dict:
    """Достаёт JSON-объект из вывода PowerShell (вокруг может быть мусор от SSH)."""
    if not raw:
        return {}
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        payload = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _append_log(db, task: TaskRun, message: str) -> None:
    task.log_output = f"{task.log_output}\n{message}" if task.log_output else message
    db.commit()


def _store_version(db, host: Host, version: str | None) -> str | None:
    """Сохраняет версию хоста. None стирает её — так проверка отмечает,
    что агент на хосте не найден, поэтому при неудачном обновлении сюда
    передавать None нельзя: прошлое значение осталось бы верным."""
    normalized = normalize_version(version)
    host.agent_version = normalized
    host.agent_version_checked_at = datetime.now(timezone.utc)
    db.commit()
    return normalized


def _ssh_port(host: Host) -> int:
    return host.ssh_port or settings.ansible_ssh_port


def _is_reachable(host: Host) -> bool:
    """TCP-проверка перед SSH — детерминированно укладывается в TCP_CHECK_TIMEOUT,
    в отличие от ожидания на уровне SSH/ansible при недоступном хосте."""
    try:
        target = resolve_host_target(host.hostname, host.ip_address)
    except ValueError:
        return False
    try:
        with socket.create_connection((target, _ssh_port(host)), timeout=TCP_CHECK_TIMEOUT):
            return True
    except OSError:
        return False


def _recheck_version(inventory: dict, host: Host, available: str | None) -> str | None:
    """Повторно опрашивает хост после обрыва сессии; None — обновление не подтвердилось."""
    for _ in range(RECHECK_ATTEMPTS):
        time.sleep(RECHECK_DELAY)
        if not _is_reachable(host):
            continue
        try:
            probe = parse_probe_output(run_raw_command(inventory, str(host.id), PROBE_CMD, timeout=PROBE_TIMEOUT))
        except Exception:  # noqa: BLE001
            continue
        version = normalize_version(probe.get("version"))
        if version and version_status(version, available) != STATUS_OUTDATED:
            return version
    return None


def _target_hosts(db, task: TaskRun) -> list[Host]:
    host_ids = [uuid.UUID(host_id) for host_id in task.host_ids]
    hosts = db.query(Host).filter(Host.id.in_(host_ids)).all() if host_ids else []
    return sorted(hosts, key=lambda h: (h.hostname or h.ip_address or str(h.id)).lower())


def _label(host: Host) -> str:
    return host.hostname or host.ip_address or str(host.id)


def _start_task(db, task: TaskRun) -> None:
    task.status = TaskStatus.running
    task.started_at = datetime.now(timezone.utc)
    db.commit()


def _finish_task(db, task: TaskRun, failed: bool) -> None:
    task.status = TaskStatus.failed if failed else TaskStatus.success
    task.finished_at = datetime.now(timezone.utc)
    db.commit()


@celery_app.task(name="services.agent_update.run_agent_version_scan")
def run_agent_version_scan(task_run_id: str):
    """Опрашивает хосты по SSH и сохраняет установленную версию агента."""
    db = SessionLocal()
    try:
        task = db.get(TaskRun, uuid.UUID(task_run_id))
        if task is None:
            return

        _start_task(db, task)
        available = available_agent_version()
        _append_log(db, task, f"Доступная версия установщика: {available or 'неизвестна'}")

        hosts = _target_hosts(db, task)
        if not hosts:
            _append_log(db, task, "Нет хостов для проверки")
            _finish_task(db, task, failed=False)
            return

        inventory = build_full_inventory(db, [host.id for host in hosts])
        any_failure = False

        for host in hosts:
            label = _label(host)
            try:
                resolve_host_target(host.hostname, host.ip_address)
                if not _is_reachable(host):
                    any_failure = True
                    _append_log(db, task, f"[{label}] недоступен по TCP {_ssh_port(host)}")
                    continue
                raw = run_raw_command(inventory, str(host.id), PROBE_CMD, timeout=PROBE_TIMEOUT)
                probe = parse_probe_output(raw)
                version = _store_version(db, host, probe.get("version"))
                if version:
                    status = version_status(version, available)
                    service = probe.get("service_status") or "неизвестно"
                    _append_log(db, task, f"[{label}] версия {version} ({status}), служба: {service}")
                else:
                    _append_log(db, task, f"[{label}] агент не найден в списке установленных программ")
            except Exception as exc:  # noqa: BLE001
                any_failure = True
                _append_log(db, task, f"[{label}] ОШИБКА: {exc}")

        _finish_task(db, task, failed=any_failure)
    except Exception as exc:  # noqa: BLE001
        task = db.get(TaskRun, uuid.UUID(task_run_id))
        if task is not None:
            _append_log(db, task, f"[ERROR] {exc}")
            _finish_task(db, task, failed=True)
    finally:
        db.close()


@celery_app.task(name="services.agent_update.run_agent_update")
def run_agent_update(task_run_id: str):
    """Ставит актуальный установщик агента поверх текущей установки на хостах."""
    db = SessionLocal()
    try:
        task = db.get(TaskRun, uuid.UUID(task_run_id))
        if task is None:
            return

        _start_task(db, task)
        available = available_agent_version()
        _append_log(db, task, f"Целевая версия: {available or 'неизвестна (установщик будет применён как есть)'}")

        hosts = _target_hosts(db, task)
        if not hosts:
            _append_log(db, task, "Нет хостов для обновления")
            _finish_task(db, task, failed=False)
            return

        inventory = build_full_inventory(db, [host.id for host in hosts])
        any_failure = False

        for host in hosts:
            label = _label(host)
            previous = host.agent_version
            try:
                if not _is_reachable(host):
                    any_failure = True
                    _append_log(db, task, f"[{label}] недоступен по TCP {_ssh_port(host)}")
                    continue
                _append_log(db, task, f"[{label}] запуск обновления (было: {previous or 'неизвестно'})")
                raw = run_raw_command(inventory, str(host.id), UPDATE_CMD, timeout=UPDATE_TIMEOUT)
                result = parse_probe_output(raw)
                version = normalize_version(result.get("version"))
                if version:
                    _store_version(db, host, version)
                exit_code = result.get("exit_code")

                if exit_code not in (0, None):
                    any_failure = True
                    _append_log(db, task, f"[{label}] установщик завершился с кодом {exit_code}")
                    continue
                if not version:
                    any_failure = True
                    _append_log(db, task, f"[{label}] не удалось подтвердить версию после установки")
                    continue

                service = result.get("service_status") or "неизвестно"
                status = version_status(version, available)
                if status == "outdated":
                    any_failure = True
                    _append_log(db, task, f"[{label}] после установки версия {version} всё ещё старее {available}")
                else:
                    _append_log(db, task, f"[{label}] обновлено: {previous or 'неизвестно'} → {version}, служба: {service}")
            except Exception as exc:  # noqa: BLE001
                # Установщик перезапускает службу агента и может задеть SSH-сессию.
                # Прежде чем считать хост упавшим, перепроверяем версию новой сессией.
                _append_log(db, task, f"[{label}] связь потеряна во время установки ({exc}); проверяем результат")
                confirmed = _recheck_version(inventory, host, available)
                if confirmed:
                    _store_version(db, host, confirmed)
                    _append_log(db, task, f"[{label}] обновлено: {previous or 'неизвестно'} → {confirmed}")
                else:
                    any_failure = True
                    _append_log(db, task, f"[{label}] ОШИБКА: обновление не подтверждено")

        _finish_task(db, task, failed=any_failure)
    except Exception as exc:  # noqa: BLE001
        task = db.get(TaskRun, uuid.UUID(task_run_id))
        if task is not None:
            _append_log(db, task, f"[ERROR] {exc}")
            _finish_task(db, task, failed=True)
    finally:
        db.close()
