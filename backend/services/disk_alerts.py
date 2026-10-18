"""Алерт disk_full: локальный диск ПК заполнен на DISK_FULL_PERCENT и больше.

Алерт — один на переход через порог, а не на каждый heartbeat: диски в тревоге хранятся в
hosts.disk_alarms. Диск снова может дать алерт, только когда освободится ниже
DISK_FULL_CLEAR_PERCENT, — иначе колебания около 90% сыпали бы алертами.
"""
from dataclasses import dataclass

from config import settings

DISK_FULL = "disk_full"


def used_percent(disk: dict) -> int | None:
    """Заполненность в целых процентах, округление как в интерфейсе (lib/hardware.ts)."""
    size = disk.get("size_bytes") or 0
    if size <= 0:
        return None
    return max(0, min(100, round((size - (disk.get("free_bytes") or 0)) / size * 100)))


def _gb(value: int) -> str:
    gb = value / 1024 ** 3
    return (f"{gb:.0f}" if gb >= 10 else f"{gb:.1f}").replace(".", ",") + " ГБ"


@dataclass
class DiskAlarms:
    alarmed: list[str]
    messages: list[str]


def check_disks(disks: list[dict], alarmed: list[str] | None) -> DiskAlarms:
    """Новые тревоги по дискам и обновлённый список дисков в тревоге."""
    previous = {name.upper() for name in (alarmed or [])}
    current: list[str] = []
    messages: list[str] = []
    for disk in disks:
        name = str(disk.get("name") or "").upper()
        percent = used_percent(disk)
        if not name or percent is None:
            continue
        if percent >= settings.disk_full_percent:
            current.append(name)
            if name not in previous:
                messages.append(f"Диск {name} заполнен на {percent}%: свободно {_gb(disk.get('free_bytes') or 0)} из {_gb(disk['size_bytes'])}")
        elif name in previous and percent >= settings.disk_full_clear_percent:
            # Ещё не освободился достаточно — тревога остаётся, повторного алерта не будет
            current.append(name)
    return DiskAlarms(alarmed=sorted(current), messages=messages)
