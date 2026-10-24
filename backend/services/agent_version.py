"""Версии FleetManager Agent: что установлено на хосте и что доступно на сервере.

Установленная версия попадает в БД тремя путями (см. routers/agent.py и
services/agent_update.py):

1. агент сам присылает её в heartbeat (`agent_version`) — самый быстрый путь;
2. если агент старый и поля не присылает, версия достаётся из инвентаризации ПО,
   которую он же и прислал: Inno Setup регистрирует запись удаления с
   DisplayName = "FleetManager Agent";
3. точечная проверка по SSH (agent_version_scan) — работает даже когда служба
   агента не запущена.

Доступная версия — тег последнего релиза из sidecar-файла, который пишет
services/agent_installer_sync.py.
"""

import hashlib
import os
import re
import threading

from config import settings

AGENT_DISPLAY_NAME = "FleetManager Agent"
INSTALLER_FILENAME = "FleetManagerAgent-Setup.exe"
VERSION_SIDECAR = INSTALLER_FILENAME + ".version"

# Статусы версии агента на хосте.
STATUS_NO_AGENT = "no_agent"        # хост заведён вручную, агента на нём нет
STATUS_UNKNOWN = "unknown"          # версия установленного агента или доступная неизвестна
STATUS_UP_TO_DATE = "up_to_date"
STATUS_OUTDATED = "outdated"
STATUS_NEWER = "newer"              # на хосте версия свежее, чем в папке установочников


def normalize_version(value: str | None) -> str | None:
    """`v2025.08.14.12` → `2025.08.14.12`; пустые значения → None."""
    if not value:
        return None
    normalized = value.strip().lstrip("vV").strip()
    return normalized or None


def parse_version(value: str | None) -> tuple[int, ...] | None:
    """Числовое представление версии для сравнения; None, если чисел нет."""
    normalized = normalize_version(value)
    if not normalized:
        return None
    parts = re.findall(r"\d+", normalized)
    return tuple(int(p) for p in parts) if parts else None


def compare_versions(installed: str | None, available: str | None) -> int | None:
    """-1/0/1 для installed относительно available; None — сравнить нельзя."""
    left, right = parse_version(installed), parse_version(available)
    if left is None or right is None:
        return None
    width = max(len(left), len(right))
    left += (0,) * (width - len(left))
    right += (0,) * (width - len(right))
    return (left > right) - (left < right)


def version_status(installed: str | None, available: str | None, *, has_agent: bool = True) -> str:
    if not has_agent:
        return STATUS_NO_AGENT
    if not normalize_version(installed) or not normalize_version(available):
        return STATUS_UNKNOWN
    order = compare_versions(installed, available)
    if order is None:
        # Нечисловые версии сравниваем только на точное совпадение.
        return STATUS_UP_TO_DATE if normalize_version(installed) == normalize_version(available) else STATUS_UNKNOWN
    if order < 0:
        return STATUS_OUTDATED
    if order > 0:
        return STATUS_NEWER
    return STATUS_UP_TO_DATE


def installer_path() -> str:
    return os.path.join(settings.soft_share_dir, INSTALLER_FILENAME)


_sha_lock = threading.Lock()
_sha_cache: dict[tuple[str, float, int], str] = {}


def installer_sha256() -> str | None:
    """SHA-256 установщика в папке установочников: агент сверяет с ним скачанный файл.

    Считается один раз на версию файла (путь, mtime, размер) — heartbeat приходит часто."""
    path = installer_path()
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (path, stat.st_mtime, stat.st_size)
    with _sha_lock:
        if key not in _sha_cache:
            digest = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    digest.update(chunk)
            _sha_cache.clear()
            _sha_cache[key] = digest.hexdigest()
        return _sha_cache[key]


# С этой версии агент обновляется сам по предложению в ответе на heartbeat (AgentSelfUpdate)
SELF_UPDATE_SINCE = "2026.10.25.0"


def agent_update_offer(host, reported_version: str | None, sshd_missing: bool = False) -> dict | None:
    """Предложение обновиться без SSH для ответа на heartbeat; снимает цель, когда она достигнута.

    Предлагается доступная сейчас версия: её и отдаёт GET /api/agent/installer.
    * цель от services/agent_update.py — версия не старее цели;
    * на ПК нет sshd (sshd_missing) — та же версия как ремонт (repair): установщик ставит sshd
      и настраивает его. Агент повторяет ремонт не больше трёх раз на версию."""
    target = host.agent_update_target
    if target and compare_versions(reported_version, target) in (0, 1):
        host.agent_update_target = None
        target = None
    if not target and not sshd_missing:
        return None
    available = available_agent_version()
    if not reported_version or not available:
        return None
    if target and compare_versions(available, target) in (None, -1):
        return None
    order = compare_versions(reported_version, available)
    if order is None or order == 1 or (order == 0 and not sshd_missing):
        return None
    if order == 0 and compare_versions(reported_version, SELF_UPDATE_SINCE) == -1:
        return None
    sha = installer_sha256()
    if not sha:
        return None
    offer = {"version": available, "sha256": sha}
    if order == 0:
        offer["repair"] = True
    return offer


def available_agent_version() -> str | None:
    """Версия установочника в папке soft_share_dir (тег последнего релиза)."""
    sidecar = os.path.join(settings.soft_share_dir, VERSION_SIDECAR)
    try:
        with open(sidecar, encoding="utf-8") as f:
            return normalize_version(f.read())
    except OSError:
        return None


def agent_version_from_software(items) -> str | None:
    """Находит версию агента в инвентаризации ПО хоста (пары «имя, версия»)."""
    for name, version in items:
        if (name or "").strip().casefold() == AGENT_DISPLAY_NAME.casefold():
            return normalize_version(version)
    return None
