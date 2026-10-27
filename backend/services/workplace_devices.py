"""Состав рабочего места и журнал изменений оборудования.

Агент с версии 2026.10.17 присылает в каждом heartbeat (раз в 5 минут) материнскую плату,
BIOS, модули памяти, физические диски, видеокарты, мониторы, клавиатуры, мыши и прочие
USB-устройства (hardware.components). Сервер сравнивает снимок с прошлым.

Появление и пропажа устройства подтверждаются, только если держатся не меньше задержки
категории (wait_for): мышь, переткнутая в другой порт, или модуль памяти, который WMI один
раз не вернул, в журнал не попадают.
- Внешние диски — 2 часа. USB-SSD с UASP (Samsung T7, Kingston XS1000) Windows показывает
  как «… SCSI Disk Device» с шиной SCSI, мимо фильтра агента по InterfaceType USB, и раньше
  каждое подключение давало алерт «Смена оборудования». Преподаватель оставляет диск на пару —
  это не изменение рабочего места. Пропажа диска, простоявшего больше 2 часов, — алерт
  «Пропало устройство».
- Память, внутренние диски, видеокарта — 30 минут, затем алерт «Смена оборудования».
  Плата и BIOS — одно значение на ПК, их смена пишется сразу (обновление BIOS — без алерта).
- Мониторы, клавиатуры, мыши, прочие USB — 30 минут; пропажа клавиатуры, мыши или
  монитора — алерт «Пропало устройство».

Состояние подтверждения хранится в hosts.hw_device_state: {ключ: {category, item, present, since}},
где present — подтверждённое состояние, since — с какого момента наблюдается обратное.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

DEBOUNCE = timedelta(minutes=30)
EXTERNAL_DISK_WAIT = timedelta(hours=2)
WAIT = {"external_disk": EXTERNAL_DISK_WAIT}

INTERNAL = ("baseboard", "bios", "memory", "disk", "gpu")
PERIPHERAL = ("monitor", "keyboard", "mouse", "usb", "external_disk")
# Отслеживаются по наличию, с задержкой; плата и BIOS — сравнением снимков
TRACKED_INTERNAL = ("memory", "disk", "gpu")
# Пропажа этих устройств — повод для алерта; прочие USB только пишутся в журнал
ALERT_ON_MISSING = {"monitor", "keyboard", "mouse", "external_disk"}
# Изменение этих компонентов — алерт «Смена оборудования»
ALERT_ON_CHANGE = {"baseboard", "memory", "disk", "gpu"}

ADDED, REMOVED, CHANGED = "added", "removed", "changed"

# Название и род: «пропала мышь», «пропал монитор», «пропало USB-устройство»
_NOUNS = {
    "baseboard": ("материнская плата", "f"),
    "bios": ("BIOS", "m"),
    "memory": ("модуль памяти", "m"),
    "disk": ("диск", "m"),
    "gpu": ("видеокарта", "f"),
    "monitor": ("монитор", "m"),
    "keyboard": ("клавиатура", "f"),
    "mouse": ("мышь", "f"),
    "usb": ("USB-устройство", "n"),
    "external_disk": ("внешний диск", "m"),
}
_VERBS = {ADDED: {"m": "Появился", "f": "Появилась", "n": "Появилось"}, REMOVED: {"m": "Пропал", "f": "Пропала", "n": "Пропало"}}

GIB = 1024 ** 3


@dataclass
class DeviceChange:
    category: str
    action: str
    summary: str
    item: dict | None = None
    previous: dict | None = None
    details: dict = field(default_factory=dict)

    @property
    def alert_type(self) -> str | None:
        if self.action == REMOVED and self.category in ALERT_ON_MISSING:
            return "device_missing"
        if self.category in ALERT_ON_CHANGE:
            return "hardware_changed"
        return None


def wait_for(category: str) -> timedelta:
    """Сколько изменение устройства этой категории должно продержаться, чтобы попасть в журнал."""
    return WAIT.get(category, DEBOUNCE)


def _size(value) -> str:
    if not value:
        return ""
    gb = value / GIB
    return f"{gb / 1024:.1f} ТБ".replace(".", ",") if gb >= 1024 else f"{round(gb)} ГБ"


def _join(*parts) -> str:
    return " ".join(str(p).strip() for p in parts if p not in (None, "") and str(p).strip())


def describe(category: str, item: dict) -> str:
    """Короткое описание для журнала: «Samsung M471A1K43EB1-CWE 8 ГБ, слот DIMM0 (с/н 424AB2C2)»."""
    serial = item.get("serial_number") or item.get("serial")
    tail = f" (с/н {serial})" if serial else ""
    if category == "memory":
        slot = f", слот {item['slot']}" if item.get("slot") else ""
        return _join(item.get("manufacturer"), item.get("part_number"), _size(item.get("capacity_bytes"))) + slot + tail
    if category in ("disk", "external_disk"):
        return _join(item.get("model"), _size(item.get("size_bytes"))) + tail
    if category == "gpu":
        return item.get("name") or "видеокарта"
    if category == "monitor":
        return _join(item.get("manufacturer"), item.get("model") or item.get("product_code")) + tail
    if category in ("keyboard", "mouse", "usb"):
        ids = f" ({item['vid']}:{item['pid']})" if item.get("vid") else ""
        return (item.get("name") or "без имени") + ids + tail
    if category == "baseboard":
        return _join(item.get("manufacturer"), item.get("product")) + tail
    return str(item)


def _summary(category: str, action: str, item: dict) -> str:
    noun, gender = _NOUNS[category]
    return f"{_VERBS[action][gender]} {noun}: {describe(category, item)}"


_VEN_DEV = re.compile(r"VEN_([0-9A-F]{4})&DEV_([0-9A-F]{4})", re.IGNORECASE)


def _gpu_key(item: dict) -> str:
    # По VEN/DEV одна и та же карта узнаётся и после переустановки драйвера, менявшей имя
    match = _VEN_DEV.search(item.get("pnp_id") or "")
    return f"{match.group(1)}:{match.group(2)}".upper() if match else (item.get("name") or "")


# Шины внутренних дисков в отчёте агента: «NVMe» или InterfaceType из Win32_DiskDrive
_INTERNAL_BUSES = {"NVME", "IDE", "SATA", "ATA", "RAID", "SAS"}
_VIRTUAL_DISK = re.compile(r"virtio|virtual|vmware|msft", re.IGNORECASE)


def is_external_disk(disk: dict) -> bool:
    """Внешний USB-диск. Агент отсекает только InterfaceType USB, а USB-SSD с UASP Windows
    показывает с шиной SCSI. Внутренние диски ПК — NVMe и IDE (SATA через AHCI); SCSI у диска
    виртуальной машины (Red Hat VirtIO SCSI Disk Device) — тоже внутренний."""
    bus = (disk.get("bus_type") or "").upper()
    if not bus or bus in _INTERNAL_BUSES:
        return False
    return not _VIRTUAL_DISK.search(disk.get("model") or "")


def _disk_key(d: dict) -> str:
    return d.get("serial_number") or f"{d.get('model')}|{d.get('size_bytes')}"


def _internal_items(components: dict, category: str) -> dict[str, dict]:
    if category == "memory":
        return {(m.get("slot") or f"#{i}"): m for i, m in enumerate(components.get("memory_modules") or [])}
    if category == "disk":
        return {_disk_key(d): d for d in components.get("physical_disks") or [] if not is_external_disk(d)}
    if category == "gpu":
        return {_gpu_key(g): g for g in components.get("gpus") or []}
    return {}


def _memory_identity(m: dict) -> tuple:
    return (m.get("manufacturer"), m.get("part_number"), m.get("serial_number"), m.get("capacity_bytes"))


def compare_internal(old: dict, new: dict) -> list[DeviceChange]:
    """Смена материнской платы и BIOS между двумя снимками. Память, диски и видеокарты
    подтверждаются с задержкой в update_peripherals."""
    changes: list[DeviceChange] = []
    old_board, new_board = old.get("baseboard") or {}, new.get("baseboard") or {}
    if old_board and new_board and (old_board.get("product"), old_board.get("serial_number")) != (new_board.get("product"), new_board.get("serial_number")):
        changes.append(DeviceChange("baseboard", CHANGED,
                                    f"Материнская плата: {describe('baseboard', old_board)} → {describe('baseboard', new_board)}",
                                    new_board, old_board))
    if old.get("bios_version") and new.get("bios_version") and old["bios_version"] != new["bios_version"]:
        changes.append(DeviceChange("bios", CHANGED, f"BIOS: {old['bios_version']} → {new['bios_version']}",
                                    {"version": new["bios_version"]}, {"version": old["bios_version"]}))
    return changes


def peripheral_items(components: dict) -> dict[str, tuple[str, dict]]:
    """Периферия снимка по ключам. Одинаковые устройства без серийного номера различаются
    порядковым номером («mouse|1C4F:0034|#2»). Клавиатура и мышь есть и среди USB-устройств
    (составное устройство) — там они не повторяются."""
    result: dict[str, tuple[str, dict]] = {}

    def add(category: str, identity: str, item: dict) -> None:
        key = f"{category}|{identity}"
        n = 1
        while f"{key}|#{n}" in result:
            n += 1
        result[f"{key}|#{n}"] = (category, item)

    for m in components.get("monitors") or []:
        add("monitor", f"{m.get('manufacturer')}:{m.get('product_code') or m.get('model')}:{m.get('serial_number') or ''}", m)
    inputs = set()
    for d in components.get("input_devices") or []:
        if d.get("kind") not in ("keyboard", "mouse"):
            continue
        inputs.add((d.get("vid"), d.get("pid")))
        add(d["kind"], f"{d.get('vid')}:{d.get('pid')}:{d.get('serial') or ''}" if d.get("vid") else (d.get("name") or ""), d)
    for d in components.get("usb_devices") or []:
        if (d.get("vid"), d.get("pid")) in inputs:
            continue
        add("usb", f"{d.get('vid')}:{d.get('pid')}:{d.get('serial') or ''}", d)
    for d in components.get("physical_disks") or []:
        if is_external_disk(d):
            add("external_disk", _disk_key(d), d)
    return result


def tracked_items(components: dict) -> dict[str, tuple[str, dict]]:
    """Всё, что подтверждается по наличию: периферия, внешние диски, память, диски, видеокарты.
    Модуль памяти узнаётся по слоту и самому модулю: другой модуль в том же слоте — замена."""
    result = peripheral_items(components)
    for category in TRACKED_INTERNAL:
        for slot, item in _internal_items(components, category).items():
            identity = f"{slot}:" + ":".join(str(v or "") for v in _memory_identity(item)) if category == "memory" else slot
            result[f"{category}|{identity}"] = (category, item)
    return result


def _merge_memory_swaps(changes: list[DeviceChange]) -> list[DeviceChange]:
    """Модуль вынули и вставили другой в тот же слот — одна запись «Память, слот …: A → B»."""
    removed = {c.previous.get("slot"): c for c in changes
               if c.category == "memory" and c.action == REMOVED and c.previous and c.previous.get("slot")}
    merged: set[int] = set()
    result = []
    for change in changes:
        old = removed.get((change.item or {}).get("slot")) if change.category == "memory" and change.action == ADDED else None
        if old is None:
            result.append(change)
            continue
        merged.add(id(old))
        result.append(DeviceChange("memory", CHANGED,
                                   f"Память, слот {change.item['slot']}: {describe('memory', old.previous)} → {describe('memory', change.item)}",
                                   change.item, old.previous, change.details))
    return [c for c in result if id(c) not in merged]


def update_peripherals(state: dict | None, components: dict, now: datetime, seed: dict | None = None) -> tuple[dict, list[DeviceChange]]:
    """Подтверждает появление и пропажу устройств, которые держатся не меньше wait_for(категория).
    Без прошлого состояния текущий состав принимается как есть, без записей в журнал.
    seed — прошлый снимок: категории, которых в состоянии ещё нет (оно велось до того, как их
    стали так отслеживать), принимаются из него как подтверждённые, без записей в журнал."""
    observed = tracked_items(components)
    if state is None:
        return {key: {"category": c, "item": item, "present": True, "since": None} for key, (c, item) in observed.items()}, []

    state = dict(state)
    if seed is not None:
        known = {e.get("category") for e in state.values()}
        for key, (category, item) in tracked_items(seed).items():
            if category not in known and key not in state:
                state[key] = {"category": category, "item": item, "present": True, "since": None}
    # Пустой список памяти, дисков или видеокарт — сбой сбора (WMI не ответил), а не вынутое железо
    blind = {c for c in TRACKED_INTERNAL if not _internal_items(components, c)}

    changes: list[DeviceChange] = []
    next_state: dict = {}
    for key in state.keys() | observed.keys():
        entry = dict(state.get(key) or {"category": observed[key][0], "item": observed[key][1], "present": False, "since": None})
        if entry["category"] in blind:
            next_state[key] = entry
            continue
        seen = key in observed
        if seen:
            entry["item"] = observed[key][1]
        if seen == entry["present"]:
            entry["since"] = None
        else:
            since = datetime.fromisoformat(entry["since"]) if entry.get("since") else None
            if since is None:
                entry["since"] = now.isoformat()
            elif now - since >= wait_for(entry["category"]):
                action = ADDED if seen else REMOVED
                changes.append(DeviceChange(entry["category"], action, _summary(entry["category"], action, entry["item"]),
                                            entry["item"] if seen else None, None if seen else entry["item"],
                                            {"since": entry["since"]}))
                entry["present"], entry["since"] = seen, None
        # Пропажа подтверждена, или появившееся не продержалось — запись больше не нужна
        if entry["present"] or entry["since"]:
            next_state[key] = entry
    return next_state, _merge_memory_swaps(sorted(changes, key=lambda c: (c.category, c.action != REMOVED)))


def apply_components(host, components: dict | None, now: datetime, same_agent_version: bool) -> list[DeviceChange]:
    """Сохраняет снимок в хосте и возвращает подтверждённые изменения. Без снимка (старый агент,
    сбой сбора) всё остаётся как было. После смены версии агента снимок принимается заново:
    другая версия может собирать поля иначе, и сравнение дало бы ложные изменения."""
    if components is None:
        return []
    previous = host.hw_components
    changes: list[DeviceChange] = []
    baseline = previous is None or not same_agent_version
    if not baseline:
        changes.extend(compare_internal(previous, components))
    state, tracked_changes = update_peripherals(None if baseline else host.hw_device_state, components, now, seed=previous)
    changes.extend(tracked_changes)
    host.hw_components = components
    host.hw_device_state = state
    return changes


def pending_devices(state: dict | None) -> list[dict]:
    """Изменения, ожидающие подтверждения: «мышь не видна 12 минут»; wait_minutes — сколько
    изменение должно продержаться, чтобы попасть в журнал."""
    return [
        {"category": e["category"], "item": e["item"], "missing": e["present"], "since": e["since"],
         "wait_minutes": int(wait_for(e["category"]).total_seconds() // 60)}
        for e in (state or {}).values()
        if e.get("since")
    ]
