import base64
import uuid
from datetime import datetime, timezone

from celery_app import celery_app
from database import SessionLocal
from models.host import Host
from models.software import InstallMethod
from models.task import TaskRun, TaskStatus
from services.ansible_runner import build_full_inventory, run_ansible
from services.host_target import resolve_host_target
from services.software_parse import parse_get_package, parse_choco_list, parse_registry_packages
from services.software_sync import sync_host_software

GET_PACKAGE_CMD = 'powershell -NoProfile -Command "Get-Package | Select-Object Name,Version | ConvertTo-Json -Compress"'
CHOCO_LIST_CMD = 'powershell -NoProfile -NonInteractive -Command "if (Get-Command choco -ErrorAction SilentlyContinue) { choco list --local-only --limit-output }"'
_LEGACY_REGISTRY_PACKAGES_CMD = (
    "powershell -NoProfile -NonInteractive -EncodedCommand "
    "JABwAGEAdABoAHMAPQBAACgAJwBIAEsATABNADoAXABTAG8AZgB0AHcAYQByAGUAXABNAGkAYwByAG8AcwBvAGYAdABcAFcAaQBuAGQAbwB3AHMAXABDAHUAcgByAGUAbgB0AFYAZQByAHMAaQBvAG4AXABVAG4AaQBuAHMAdABhAGwAbABcACoAJwAsACcASABLAEwATQA6AFwAUwBvAGYAdAB3AGEAcgBlAFwAVwBPAFcANgA0ADMAMgBOAG8AZABlAFwATQBpAGMAcgBvAHMAbwBmAHQAXABXAGkAbgBkAG8AdwBzAFwAQwB1AHIAcgBlAG4AdABWAGUAcgBzAGkAbwBuAFwAVQBuAGkAbgBzAHQAYQBsAGwAXAAqACcALAAnAEgASwBDAFUAOgBcAFMAbwBmAHQAdwBhAHIAZQBcAE0AaQBjAHIAbwBzAG8AZgB0AFwAVwBpAG4AZABvAHcAcwBcAEMAdQByAHIAZQBuAHQAVgBlAHIAcwBpAG8AbgBcAFUAbgBpAG4AcwB0AGEAbABsAFwAKgAnACkAOwAkAGkAdABlAG0AcwA9AGYAbwByAGUAYQBjAGgAKAAkAHAAYQB0AGgAIABpAG4AIAAkAHAAYQB0AGgAcwApAHsARwBlAHQALQBJAHQAZQBtAFAAcgBvAHAAZQByAHQAeQAgAC0AUABhAHQAaAAgACQAcABhAHQAaAAgAC0ARQByAHIAb3JBAWN0AGkAbwBuACAAUwBpAGwAZQBuAHQAbAB5AEMAbwBuAHQAaQBuAHUAZQAgAHwAIABXAGgAZQByAGUALQBPAGIAagBlAGMAdAAgAHsAJABfAC4ARABpAHMAcABsAGEAeQBOAGEAbQBlACAALQBhAG4AZAAgACQAXwAuAFMAeQBzAHQAZQBtAEMAbwBtAHAAbwBuAGUAbgB0ACAALQBuAGUAIAAxAH0AIAB8ACAARgBvAHIARQBhAGMAaAAtAE8AYgBqAGUAYwB0ACAAewBbAHAAcwBjAHUAcwB0AG8AbQBvAGIAagBlAGMAdABdAEAAewBOAGEAbQBlAD0AJABfAC4ARABpAHMAcABsAGEAeQBOAGEAbQBlADsAVgBlAHIAcwBpAG8AbgA9ACgAWwBzAHQAcgBpAG4AZwBdACQAXwAuAEQAaQBzAHAAbABhAHkAVgBlAHIAcwBpAG8AbgApAH0AfQB9ADsAJABpAHQAZQBtAHMAIAB8ACAAUwBvAHIAdAAtAE8AYgBqAGUAYwB0ACAATgBhAG0AZQAsAFYAZQByAHMAaQBvAG4AIAAtAFUAbgBpAHEAdQBlACAAfAAgAEMAbwBuAHYAZQByAHQAVABvAC0ASgBzAG8AbgAgAC0AQwBvAG0AcAByAGUAcwBzAA=="
)

REGISTRY_PACKAGES_CMD = (
    "powershell -NoProfile -NonInteractive -EncodedCommand "
    "JABwAGEAdABoAHMAPQAnAEgASwBMAE0AOgBcAFMAbwBmAHQAdwBhAHIAZQBcAE0AaQBjAHIAbwBzAG8AZgB0AFwAVwBpAG4AZABvAHcAcwBcAEMAdQByAHIAZQBuAHQAVgBlAHIAcwBpAG8AbgBcAFUAbgBpAG4AcwB0AGEAbABsAFwAKgAnACwAJwBIAEsATABNADoAXABTAG8AZgB0AHcAYQByAGUAXABXAE8AVwA2ADQAMwAyAE4AbwBkAGUAXABNAGkAYwByAG8AcwBvAGYAdABcAFcAaQBuAGQAbwB3AHMAXABDAHUAcgByAGUAbgB0AFYAZQByAHMAaQBvAG4AXABVAG4AaW5zdGFsbABcACoAJwAsACcASABLAEMAVQA6AFwAUwBvAGYAdAB3AGEAcgBlAFwATQBpAGMAcgBvAHMAb2YAdABcAFcAaW5kb3dzXEN1cnJlbnRWZXJzaW9uXFVuaW5zdGFsbFwqACcAOwAkAGkAdABlAG0AcwA9AGYAb3JlYWNoACgAJABwACAAaW4AIAAkAHAAYQB0AGgAcwApAHsARwBlAHQALQBJAHQAZQBtAFAAcgBvAHAAZQByAHQAeQAgACQAcAAgAC0ARQByAHIAb3JBAWN0AGkAbwBuACAAUwBpAGwAZQBuAHQAbAB5AEMAbwBuAHQAaQBuAHUAZQAgAHwAIAA/ACAAewAkAF8ALgBEAGkAcwBwAGwAYQB5AE4AYQBtAGUAIAAtAGEAbgBkACAAJABfAC4AUwB5AHMAdABlAG0AQwBvAG0AcABvAG4AZQBuAHQAIAAtAG4AZQAgADEAfQAgAHwAIAAlACAAewBbAHAAcwBjAHUAcwB0AG8AbQBvAGIAagBlAGMAdABdAEAAewBOAGEAbQBlAD0AJABfAC4ARABpAHMAcABsAGEAeQBOAGEAbQBlADsAVgBlAHIAcwBpAG8AbgA9AFsAcwB0AHIAaQBuAGcAXQAkAF8ALgBEAGkAcwBwAGwAYQB5AFYAZQByAHMAaQBvAG4AfQB9AH0AOwAkAGkAdABlAG0AcwAgAHwAIABTAG8AcgB0ACAATgBhAG0AZQAsAFYAZQByAHMAaQBvAG4AIAAtAFUAbgBpAHEAdQBlACAAfAAgAEMAbwBuAHYAZQByAHQAVABvAC0ASgBzAG8AbgAgAC0AQwBvAG0AcAByAGUAcwBzAA=="
)


# Use an encoded PowerShell payload so the remote Windows shell cannot strip
# registry paths, variables, or quoting before PowerShell receives them.
REGISTRY_PACKAGES_CMD = (
    "powershell -NoProfile -NonInteractive -EncodedCommand "
    "JABpAHQAZQBtAHMAPQBHAGUAdAAtAEkAdABlAG0AUAByAG8AcABlAHIAdAB5ACAAJwBIAEsATABNADoAXABTAG8AZgB0AHcAYQByAGUAXABNAGkAYwByAG8AcwBvAGYAdABcAFcAaQBuAGQAbwB3AHMAXABDAHUAcgByAGUAbgB0AFYAZQByAHMAaQBvAG4AXABVAG4AaW5zdGFsbABcACoAJwAsACcASABLAEwATQA6AFwAUwBvAGYAdAB3AGEAcgBlAFwAVwBPAFcANgA0ADMAMgBOAG8AZABlAFwATQBpAGMAcgBvAHMAb2YAdABcAFcAaQBuAGQAbwB3AHMAXABDAHUAcgByAGUAbgB0AFYAZQByAHMAaQBvAG4AXABVAG4AaW5zdGFsbABcACoAJwAsACcASABLAEMAVQA6AFwAUwBvAGYAdwBhAHIAZQBcAE0AaQBjAHIAb3NvZnRcAFcAaW5kb3dzXEN1cnJlbnRWZXJzaW9uXFVuaW5zdGFsbFwqACcAIAAtAEUAcgByAG8AcgBBAGMAdABpAG8AbgAgAFMAaQBsAGUAbgB0AGwAeQBDAG8AbgB0AGkAbgB1AGUAIAB8ACAAPwAgAHsAJABfAC4ARABpAHMAcABsAGEAeQBOAGEAbQBlACAALQBhAG4AZAAgACQAXwAuAFMAeQBzAHQAZQBtAEMAbwBtAHAAbwBuAGUAbgB0ACAALQBuAGUAIAAxAH0AIAB8ACAAlACAAewBbAHAAcwBjdQBzAHQAbwBtAG8AYgBqAGUAYwB0AF0AQAB7AE4AYQBtAGUAPQAkAF8ALgBEAGkAcwBwAGwAYQB5AE4AYQBtAGUAOwBWAGUAcgBzAGkAbwBuAD0AWwBzAHQAcgBpAG4AZwBdACQAXwAuAEQAaQBzAHAAbABhAHkAVgBlAHIAcwBpAG8AbgB9AH0AOwAkAGkAdABlAG0AcwAgAHwAIABTAG8AcgB0ACAATgBhAG0AZQAsAFYAZQByAHMAaQBvAG4AIAAtAFUAbgBpAHEAdQBlACAAfAAgAEMAbwBuAHYAZQByAHQAVABvAC0ASgBzAG8AbgAgAC0AQwBvAG0AcAByAGUAcwBzAA=="
)


REGISTRY_SCRIPT = r"""$items=Get-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*','HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -and $_.SystemComponent -ne 1 } | ForEach-Object { [pscustomobject]@{ Name=$_.DisplayName; Version=[string]$_.DisplayVersion } }; $items | Sort-Object Name,Version -Unique | ConvertTo-Json -Compress"""
REGISTRY_PACKAGES_CMD = "powershell -NoProfile -NonInteractive -EncodedCommand " + base64.b64encode(REGISTRY_SCRIPT.encode("utf-16le")).decode("ascii")


REGISTRY_SCRIPT = r"""$items=Get-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*','HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -and $_.SystemComponent -ne 1 } | ForEach-Object { [pscustomobject]@{ Name=$_.DisplayName; Version=[string]$_.DisplayVersion } }; $appx=Get-AppxPackage -ErrorAction SilentlyContinue | Where-Object { $_.Name -and $_.IsFramework -ne $true } | ForEach-Object { [pscustomobject]@{ Name=$_.Name; Version=[string]$_.Version } }; @($items)+=@($appx); $items | Sort-Object Name,Version -Unique | ConvertTo-Json -Compress"""
REGISTRY_PACKAGES_CMD = "powershell -NoProfile -NonInteractive -EncodedCommand " + base64.b64encode(REGISTRY_SCRIPT.encode("utf-16le")).decode("ascii")


REGISTRY_SCRIPT = r"""$items=Get-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*','HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -and $_.SystemComponent -ne 1 } | ForEach-Object { [pscustomobject]@{ Name=$_.DisplayName; Version=[string]$_.DisplayVersion } }; $appx=Get-AppxPackage -ErrorAction SilentlyContinue | Where-Object { $_.Name -and $_.IsFramework -ne $true } | ForEach-Object { [pscustomobject]@{ Name=$_.Name; Version=[string]$_.Version } }; $items=@($items)+@($appx); $items | Sort-Object Name,Version -Unique | ConvertTo-Json -Compress"""
REGISTRY_PACKAGES_CMD = "powershell -NoProfile -NonInteractive -EncodedCommand " + base64.b64encode(REGISTRY_SCRIPT.encode("utf-16le")).decode("ascii")


def _run_raw(inventory: dict, inventory_host: str, command: str) -> str:
    result = run_ansible(
        module="ansible.builtin.raw",
        module_args=command,
        host_pattern=inventory_host,
        inventory=inventory,
        quiet=True,
    )
    output_parts = []
    failure_msg = None
    for event in result.events:
        event_data = event.get("event_data", {})
        if event_data.get("host") != inventory_host:
            continue

        res = event_data.get("res") or {}
        if event.get("event") in ("runner_on_unreachable", "runner_on_failed"):
            failure_msg = res.get("msg") or event_data.get("res", {}).get("stdout") or event.get("event")
        stdout = res.get("stdout")
        if stdout:
            output_parts.append(stdout)

    if failure_msg is not None:
        raise RuntimeError(f"Ansible: {failure_msg}")

    return "\n".join(output_parts)


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
        hosts = db.query(Host).filter(Host.id.in_(host_ids)).all()
        inventory = build_full_inventory(db, host_ids)

        log_lines: list[str] = []
        any_failure = False

        for host in hosts:
            try:
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
                log_lines.append(f"[{display_target}] обнаружено пакетов: {len(discovered)}")
            except Exception as exc:  # noqa: BLE001
                any_failure = True
                log_lines.append(f"[{host.hostname or host.ip_address}] ОШИБКА: {exc}")

            task_run.log_output = "\n".join(log_lines)
            db.commit()

        task_run.status = TaskStatus.failed if any_failure else TaskStatus.success
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
