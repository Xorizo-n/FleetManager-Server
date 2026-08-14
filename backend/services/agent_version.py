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

import os
import re

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
