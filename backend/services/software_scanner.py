import base64
import uuid
from datetime import datetime, timezone

from celery_app import celery_app
from database import SessionLocal
from models.host import Host
from models.software import InstallMethod
from models.task import TaskRun, TaskStatus
from services.agent_version import agent_version_from_software
from services.ansible_runner import build_full_inventory, run_raw_command
from services.host_parallel import HostOutcome, append_task_log, run_for_hosts
from services.host_target import resolve_host_target
from services.software_parse import parse_get_package, parse_choco_list, parse_registry_packages
from services.software_sync import sync_host_software

GET_PACKAGE_CMD = 'powershell -NoProfile -Command "Get-Package | Select-Object Name,Version | ConvertTo-Json -Compress"'
CHOCO_LIST_CMD = 'powershell -NoProfile -NonInteractive -Command "if (Get-Command choco -ErrorAction SilentlyContinue) { choco list --local-only --limit-output }"'

# Uninstall-записи читаются по ключам через RegistryKey.GetValue, а не
# Get-ItemProperty по маске: тот читает все значения всех записей, и одно чужое
# битое значение роняет весь вызов. Установщик NetBeans пишет NoModify как
# REG_DWORD из 8 байт, .NET отдаёт его как Int64, провайдер реестра PowerShell
# падает с InvalidCastException, и на таком ПК (SU5-VM-SBX) из реестра не
# находилось ни одной программы. Нечитаемая запись пропускается, остальные — нет.
REGISTRY_SCRIPT = r"""$keys='HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall','HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall'; $items=Get-ChildItem $keys -ErrorAction SilentlyContinue | ForEach-Object { try { $name=[string]$_.GetValue('DisplayName'); if ($name -and $_.GetValue('SystemComponent') -ne 1) { [pscustomobject]@{ Name=$name; Version=[string]$_.GetValue('DisplayVersion') } } } catch {} }; $appx=Get-AppxPackage -ErrorAction SilentlyContinue | Where-Object { $_.Name -and $_.IsFramework -ne $true } | ForEach-Object { [pscustomobject]@{ Name=$_.Name; Version=[string]$_.Version } }; $items=@($items)+@($appx); $items | Sort-Object Name,Version -Unique | ConvertTo-Json -Compress"""
# Закодированный PowerShell: удалённый shell не портит пути, переменные и кавычки.
REGISTRY_PACKAGES_CMD = "powershell -NoProfile -NonInteractive -EncodedCommand " + base64.b64encode(REGISTRY_SCRIPT.encode("utf-16le")).decode("ascii")


def _run_raw(inventory: dict, inventory_host: str, command: str) -> str:
    return run_raw_command(inventory, inventory_host, command)


def _scan_host(db, task_id: uuid.UUID, inventory: dict, host: Host) -> HostOutcome:
    inventory_host = str(host.id)
    display_target = resolve_host_target(host.hostname, host.ip_address)
    registry_raw = _run_raw(inventory, inventory_host, REGISTRY_PACKAGES_CMD)
    pkg_raw = _run_raw(inventory, inventory_host, GET_PACKAGE_CMD)
    choco_raw = _run_raw(inventory, inventory_host, CHOCO_LIST_CMD)

    discovered: dict[str, tuple[str, InstallMethod]] = {}
    registry_packages = parse_registry_packages(registry_raw)
    package_provider_packages = parse_get_package(pkg_raw)
    chocolatey_packages = parse_choco_list(choco_raw)
    for name, version in registry_packages:
        discovered[name] = (version, InstallMethod.msi)
    for name, version in package_provider_packages:
        discovered[name] = (version, InstallMethod.msi)
    for name, version in chocolatey_packages:
        discovered[name] = (version, InstallMethod.chocolatey)

    sync_host_software(db, host, discovered)

    # Сканирование реестра заодно показывает версию самого агента —
    # это бесплатный источник данных для страницы версий агента.
    agent_version = agent_version_from_software(
        (name, version) for name, (version, _method) in discovered.items()
    )
    if agent_version:
        host.agent_version = agent_version
        host.agent_version_checked_at = datetime.now(timezone.utc)
        db.commit()

    append_task_log(db, task_id, f"[{display_target}] обнаружено пакетов: {len(discovered)}")
    return HostOutcome.ok


@celery_app.task(name="services.software_scanner.scan_software_task")
def scan_software_task(task_run_id: str):
    db = SessionLocal()
    try:
        task_run = db.get(TaskRun, uuid.UUID(task_run_id))
        if task_run is None:
            return

        task_run.status = TaskStatus.running
        task_run.started_at = datetime.now(timezone.utc)
        db.commit()

        host_ids = [uuid.UUID(h) for h in task_run.host_ids]
        inventory = build_full_inventory(db, host_ids)
        any_failure = run_for_hosts(
            task_run.id, host_ids,
            lambda host_db, host: _scan_host(host_db, task_run.id, inventory, host),
        )

        task_run.status = TaskStatus.failed if any_failure else TaskStatus.success
        task_run.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        task_run = db.get(TaskRun, uuid.UUID(task_run_id))
        if task_run:
            append_task_log(db, task_run.id, f"[ERROR] {exc}")
            task_run.status = TaskStatus.failed
            task_run.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
