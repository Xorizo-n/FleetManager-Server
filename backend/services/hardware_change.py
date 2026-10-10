"""Hardware changes detected by the server from heartbeats.

The agent's own alert carries only two fingerprint hashes ("Hardware fingerprint
changed."), so it says nothing about what changed, and it fired falsely whenever
the localized OS name switched language. The server keeps the last reported
hardware and compares it with each heartbeat instead, naming the changed parts.
"""

from models.host import Host

GIB = 1024 ** 3

# Field of the host, field of AgentHardware, label in the alert
FIELDS = (
    ("hw_manufacturer", "manufacturer", "Производитель"),
    ("hw_model", "model", "Модель"),
    ("hw_serial_number", "serial_number", "Серийный номер"),
    ("hw_processor", "processor", "Процессор"),
    ("hw_total_memory_bytes", "total_memory_bytes", "Память"),
)


def _memory_gb(value) -> int | None:
    # Сравниваются целые гигабайты: доли от резерва прошивки и видеоядра — не замена памяти
    return round(value / GIB) if value else None


def _comparable(field: str, value):
    if field == "hw_total_memory_bytes":
        return _memory_gb(value)
    return value.strip() if isinstance(value, str) else value


def _shown(field: str, value) -> str:
    if field == "hw_total_memory_bytes":
        return f"{_memory_gb(value)} ГБ"
    return str(value)


def hardware_changes(host: Host, hardware, agent_version: str | None) -> list[str]:
    """What changed between the stored hardware of the host and a heartbeat, e.g.
    ["Память: 16 ГБ → 8 ГБ"]. Empty when nothing is comparable:

    - only reports of the same agent version are compared (hosts.hw_agent_version):
      another version may collect fields differently — script agents reported the
      disk model as the serial number;
    - the OS name is not compared: it is not hardware, and old agents reported it
      in the interface language;
    - a part is compared only when both values are known (the agent may fail to
      read it once).
    """
    if not agent_version or host.hw_agent_version != agent_version:
        return []
    changes = []
    for host_field, hardware_field, label in FIELDS:
        old = getattr(host, host_field)
        new = getattr(hardware, hardware_field)
        if old in (None, "") or new in (None, ""):
            continue
        if _comparable(host_field, old) != _comparable(host_field, new):
            changes.append(f"{label}: {_shown(host_field, old)} → {_shown(host_field, new)}")
    return changes
