"""Состав рабочего места и журнал изменений оборудования.

Агент с версии 2026.10.17 присылает в каждом heartbeat (раз в 5 минут) материнскую плату,
BIOS, модули памяти, физические диски, видеокарты, мониторы, клавиатуры, мыши и прочие
USB-устройства (hardware.components). Сервер сравнивает снимок с прошлым:

- внутренние компоненты (плата, память, диски, видеокарта) меняются только при вскрытии
  корпуса — изменение сразу пишется в журнал и даёт алерт «Смена оборудования»; обновление
  BIOS только пишется в журнал;
- периферию переподключают постоянно, поэтому её изменение подтверждается, только если
  держится DEBOUNCE: мышь, переткнутая в другой порт или отключённая на пять минут, в журнал
  не попадает. Пропажа клавиатуры, мыши или монитора даёт алерт «Пропало устройство».

Состояние подтверждения хранится в hosts.hw_device_state: {ключ: {category, item, present, since}},
где present — подтверждённое состояние, since — с какого момента наблюдается обратное.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

DEBOUNCE = timedelta(minutes=30)

INTERNAL = ("baseboard", "bios", "memory", "disk", "gpu")
PERIPHERAL = ("monitor", "keyboard", "mouse", "usb")
# Пропажа этих устройств — повод для алерта; прочие USB только пишутся в журнал
ALERT_ON_MISSING = {"monitor", "keyboard", "mouse"}
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
    if category == "disk":
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


def _internal_items(components: dict, category: str) -> dict[str, dict]:
    if category == "memory":
        return {(m.get("slot") or f"#{i}"): m for i, m in enumerate(components.get("memory_modules") or [])}
    if category == "disk":
        return {(d.get("serial_number") or f"{d.get('model')}|{d.get('size_bytes')}"): d for d in components.get("physical_disks") or []}
    if category == "gpu":
        return {_gpu_key(g): g for g in components.get("gpus") or []}
    return {}


def _memory_identity(m: dict) -> tuple:
    return (m.get("manufacturer"), m.get("part_number"), m.get("serial_number"), m.get("capacity_bytes"))


def compare_internal(old: dict, new: dict) -> list[DeviceChange]:
    """Изменения платы, BIOS, памяти, дисков и видеокарт между двумя снимками."""
    changes: list[DeviceChange] = []
    old_board, new_board = old.get("baseboard") or {}, new.get("baseboard") or {}
    if old_board and new_board and (old_board.get("product"), old_board.get("serial_number")) != (new_board.get("product"), new_board.get("serial_number")):
        changes.append(DeviceChange("baseboard", CHANGED,
                                    f"Материнская плата: {describe('baseboard', old_board)} → {describe('baseboard', new_board)}",
                                    new_board, old_board))
    if old.get("bios_version") and new.get("bios_version") and old["bios_version"] != new["bios_version"]:
        changes.append(DeviceChange("bios", CHANGED, f"BIOS: {old['bios_version']} → {new['bios_version']}",
                                    {"version": new["bios_version"]}, {"version": old["bios_version"]}))
    for category in ("memory", "disk", "gpu"):
        before, after = _internal_items(old, category), _internal_items(new, category)
        # Пустой список при непустом прошлом — сбой сбора (WMI не ответил), а не вынутая память
        if before and not after:
            continue
        for key in before.keys() - after.keys():
            changes.append(DeviceChange(category, REMOVED, _summary(category, REMOVED, before[key]), None, before[key]))
        for key in after.keys() - before.keys():
            changes.append(DeviceChange(category, ADDED, _summary(category, ADDED, after[key]), after[key]))
        if category == "memory":
            for key in before.keys() & after.keys():
                if _memory_identity(before[key]) != _memory_identity(after[key]):
                    changes.append(DeviceChange(category, CHANGED,
                                                f"Память, слот {key}: {describe('memory', before[key])} → {describe('memory', after[key])}",
                                                after[key], before[key]))
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
    return result


def update_peripherals(state: dict | None, components: dict, now: datetime) -> tuple[dict, list[DeviceChange]]:
    """Подтверждает появление и пропажу периферии, которые держатся не меньше DEBOUNCE.
    Без прошлого состояния текущая периферия принимается как есть, без записей в журнал."""
    observed = peripheral_items(components)
    if state is None:
        return {key: {"category": c, "item": item, "present": True, "since": None} for key, (c, item) in observed.items()}, []

    changes: list[DeviceChange] = []
    next_state: dict = {}
    for key in state.keys() | observed.keys():
        entry = dict(state.get(key) or {"category": observed[key][0], "item": observed[key][1], "present": False, "since": None})
        seen = key in observed
        if seen:
            entry["item"] = observed[key][1]
        if seen == entry["present"]:
            entry["since"] = None
        else:
            since = datetime.fromisoformat(entry["since"]) if entry.get("since") else None
            if since is None:
                entry["since"] = now.isoformat()
            elif now - since >= DEBOUNCE:
                action = ADDED if seen else REMOVED
                changes.append(DeviceChange(entry["category"], action, _summary(entry["category"], action, entry["item"]),
                                            entry["item"] if seen else None, None if seen else entry["item"],
                                            {"since": entry["since"]}))
                entry["present"], entry["since"] = seen, None
        # Пропажа подтверждена, или появившееся не продержалось — запись больше не нужна
        if entry["present"] or entry["since"]:
            next_state[key] = entry
    return next_state, changes


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
    state, peripheral_changes = update_peripherals(None if baseline else host.hw_device_state, components, now)
    changes.extend(peripheral_changes)
    host.hw_components = components
    host.hw_device_state = state
    return changes


def pending_devices(state: dict | None) -> list[dict]:
    """Изменения, ожидающие подтверждения: «мышь не видна 12 минут»."""
    return [
        {"category": e["category"], "item": e["item"], "missing": e["present"], "since": e["since"]}
        for e in (state or {}).values()
        if e.get("since")
    ]
