"""Пробуждение ПК по сети (Wake-on-LAN).

Сервер в другой сети и широковещательный магический пакет до ПК не донесёт.
Поэтому пакет отправляет включённый ПК из той же подсети: по SSH, тем же
каналом, что и вся остальная автоматизация. MAC и подсеть (IPv4/префикс) ПК
сообщает агент в heartbeat (hosts.hw_network_adapters).

ПК подготавливает к пробуждению установщик агента: проводной адаптер будит
компьютер, быстрый запуск выключен. В BIOS пробуждение по сети должно быть
разрешено — это удалённо не сделать.
"""

import ipaddress
import re
import socket
import time
import uuid
from datetime import datetime, timezone

from celery_app import celery_app
from config import settings
from database import SessionLocal
from models.host import Host, HostStatus
from models.task import TaskRun, TaskStatus
from services.agent_update import encode_powershell
from services.ansible_runner import build_full_inventory, run_raw_command

# Сколько ждать, пока проснувшийся ПК ответит по SSH или пришлёт heartbeat:
# загрузка плюс отложенный запуск агента — обычно 2–4 минуты.
WAKE_WAIT_SECONDS = 420
WAKE_POLL_SECONDS = 15
RELAY_ATTEMPTS = 3
RELAY_TIMEOUT = 60
TCP_CHECK_TIMEOUT = 3

def normalize_mac(value: str | None) -> str | None:
    """«34:5a:60:bf:91:c7», «345A60BF91C7» → «34-5A-60-BF-91-C7» (как в Windows)."""
    if not value:
        return None
    digits = re.sub(r"[^0-9A-Fa-f]", "", value)
    if len(digits) != 12 or digits in ("000000000000", "FFFFFFFFFFFF"):
        return None
    return "-".join(digits[i:i + 2] for i in range(0, 12, 2)).upper()


def _interfaces(adapter: dict) -> list[ipaddress.IPv4Interface]:
    result = []
    for entry in adapter.get("ipv4") or []:
        try:
            result.append(ipaddress.IPv4Interface(entry if "/" in entry else f"{entry}/32"))
        except ValueError:
            continue
    return result


def _usable(interface: ipaddress.IPv4Interface) -> bool:
    return not (interface.ip.is_link_local or interface.ip.is_loopback or interface.ip.is_unspecified)


def agent_lan_address(adapters: list[dict] | None, source_ip: str | None) -> str | None:
    """Адрес ПК в локальной сети для SSH/RDP/WoL.

    Обычно heartbeat приходит с адреса самого ПК. Но если на ПК поднят VPN, через
    который идёт и трафик к серверу (встроенный клиент Windows на SU5), сервер видит
    адрес из пула VPN — до ПК по нему не достучаться. Тогда берётся адрес физического
    адаптера: проводного в сети, иначе любого подключённого. Без адаптеров (старый
    агент) остаётся адрес источника.
    """
    if not adapters:
        return source_ip
    if source_ip and any(str(i.ip) == source_ip for a in adapters for i in _interfaces(a)):
        return source_ip
    up = [a for a in adapters if (a.get("status") or "").lower() == "up"]
    wired = [a for a in up if (a.get("media_type") or "") == "802.3"]
    for adapter in wired + [a for a in up if a not in wired]:
        for interface in _interfaces(adapter):
            if _usable(interface):
                return str(interface.ip)
    return source_ip


def primary_adapter(adapters: list[dict] | None, host_ip: str | None) -> dict | None:
    """Адаптер, через который ПК пришёл на сервер; иначе проводной в сети, иначе любой проводной."""
    candidates = [a for a in adapters or [] if normalize_mac(a.get("mac_address"))]
    if not candidates:
        return None
    if host_ip:
        for adapter in candidates:
            if any(str(i.ip) == host_ip for i in _interfaces(adapter)):
                return adapter
    wired = [a for a in candidates if (a.get("media_type") or "") == "802.3"]
    for adapter in wired:
        if (adapter.get("status") or "").lower() == "up":
            return adapter
    return (wired or candidates)[0]


def wake_target(host: Host) -> tuple[str | None, ipaddress.IPv4Network | None, bool]:
    """(MAC, подсеть, подсеть известна точно). Без префикса от агента берётся /24 вокруг IP хоста."""
    adapter = primary_adapter(host.hw_network_adapters, host.ip_address)
    mac = normalize_mac(adapter.get("mac_address")) if adapter else normalize_mac(host.hw_mac_address)
    if adapter:
        for interface in _interfaces(adapter):
            if interface.network.prefixlen < 32 and (not host.ip_address or str(interface.ip) == host.ip_address):
                return mac, interface.network, True
    try:
        return mac, ipaddress.IPv4Network(f"{host.ip_address}/24", strict=False), False
    except (ValueError, TypeError):
        return mac, None, False


def magic_packet_script(macs: list[str], network: ipaddress.IPv4Network) -> str:
    """PowerShell для соседа: магический пакет на 255.255.255.255 и на широковещательный адрес подсети, порты 7 и 9."""
    mac_list = ",".join(f"'{mac}'" for mac in macs)
    return f"""
$ErrorActionPreference = 'Stop'
$udp = New-Object Net.Sockets.UdpClient
$udp.EnableBroadcast = $true
$sent = 0
foreach ($mac in @({mac_list})) {{
    $bytes = [byte[]]($mac -split '-' | ForEach-Object {{ [Convert]::ToByte($_, 16) }})
    $packet = [byte[]](,0xFF * 6) + ($bytes * 16)
    foreach ($target in '255.255.255.255', '{network.broadcast_address}') {{
        foreach ($port in 7, 9) {{ [void]$udp.Send($packet, $packet.Length, $target, $port); $sent++ }}
    }}
}}
$udp.Close()
"fleet-wol-sent=$sent"
"""


def relay_candidates(db, network: ipaddress.IPv4Network, exclude: set[str]) -> list[Host]:
    """Включённые ПК той же подсети, последние по heartbeat — первыми."""
    hosts = db.query(Host).filter(Host.status == HostStatus.online, Host.ip_address.isnot(None)).all()
    result = []
    for host in hosts:
        if str(host.id) in exclude:
            continue
        try:
            if ipaddress.IPv4Address(host.ip_address) in network:
                result.append(host)
        except ValueError:
            continue
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(result, key=lambda h: h.last_seen_at or epoch, reverse=True)


def _append_log(db, task: TaskRun, message: str) -> None:
    task.log_output = f"{task.log_output}\n{message}" if task.log_output else message
    db.commit()


def _label(host: Host) -> str:
    return host.hostname or host.ip_address or str(host.id)


def _tcp_open(ip: str | None, port: int) -> bool:
    if not ip:
        return False
    try:
        with socket.create_connection((ip, port), timeout=TCP_CHECK_TIMEOUT):
            return True
    except OSError:
        return False


def _send_via_relay(db, task: TaskRun, network, macs: list[str], exclude: set[str]) -> Host | None:
    command = encode_powershell(magic_packet_script(macs, network))
    for relay in relay_candidates(db, network, exclude)[:RELAY_ATTEMPTS]:
        if not _tcp_open(relay.ip_address, relay.ssh_port or settings.ansible_ssh_port):
            _append_log(db, task, f"  {_label(relay)}: не отвечает по SSH, пробуем другого соседа")
            continue
        try:
            output = run_raw_command(build_full_inventory(db, [relay.id]), str(relay.id), command, timeout=RELAY_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            _append_log(db, task, f"  {_label(relay)}: не удалось отправить ({exc})")
            continue
        if "fleet-wol-sent=" in output:
            return relay
        _append_log(db, task, f"  {_label(relay)}: неожиданный ответ, пробуем другого соседа")
    return None


@celery_app.task(name="services.wake_on_lan.run_host_wake")
def run_host_wake(task_run_id: str):
    db = SessionLocal()
    try:
        task = db.get(TaskRun, uuid.UUID(task_run_id))
        if task is None:
            return
        task.status = TaskStatus.running
        task.started_at = datetime.now(timezone.utc)
        db.commit()

        hosts = db.query(Host).filter(Host.id.in_([uuid.UUID(h) for h in task.host_ids])).all()
        targets: dict[ipaddress.IPv4Network, list[tuple[Host, str]]] = {}
        failed = False
        for host in sorted(hosts, key=_label):
            if host.status == HostStatus.online:
                _append_log(db, task, f"[{_label(host)}] уже в сети")
                continue
            mac, network, exact = wake_target(host)
            if not mac:
                failed = True
                _append_log(db, task, f"[{_label(host)}] MAC неизвестен: агент сообщает его с версии 2026.10.12, обновится при следующем включении")
                continue
            if network is None:
                failed = True
                _append_log(db, task, f"[{_label(host)}] неизвестен IP — не понять, через кого отправить пакет")
                continue
            note = "" if exact else " (подсеть предположена по IP: агент не сообщил маску)"
            _append_log(db, task, f"[{_label(host)}] MAC {mac}, подсеть {network}{note}")
            targets.setdefault(network, []).append((host, mac))

        exclude = {str(h.id) for h in hosts}
        woken: list[Host] = []
        for network, items in targets.items():
            relay = _send_via_relay(db, task, network, [mac for _, mac in items], exclude)
            names = ", ".join(_label(h) for h, _ in items)
            if relay is None:
                failed = True
                _append_log(db, task, f"Подсеть {network}: нет включённого ПК с рабочим SSH, пакет не отправлен ({names})")
                continue
            _append_log(db, task, f"Подсеть {network}: магический пакет отправлен через {_label(relay)} → {names}")
            woken.extend(h for h, _ in items)

        if woken:
            _append_log(db, task, f"Ждём ответа до {WAKE_WAIT_SECONDS // 60} мин: SSH или heartbeat агента")
            sent_at = datetime.now(timezone.utc)
            pending = {h.id: h for h in woken}
            deadline = time.monotonic() + WAKE_WAIT_SECONDS
            while pending and time.monotonic() < deadline:
                time.sleep(WAKE_POLL_SECONDS)
                for host_id, host in list(pending.items()):
                    db.refresh(host)
                    heartbeat = host.last_seen_at is not None and host.last_seen_at > sent_at
                    if heartbeat or _tcp_open(host.ip_address, host.ssh_port or settings.ansible_ssh_port):
                        seconds = int((datetime.now(timezone.utc) - sent_at).total_seconds())
                        _append_log(db, task, f"[{_label(host)}] проснулся через {seconds} с ({'heartbeat' if heartbeat else 'SSH отвечает'})")
                        pending.pop(host_id)
            for host in pending.values():
                failed = True
                _append_log(
                    db, task,
                    f"[{_label(host)}] не ответил за {WAKE_WAIT_SECONDS // 60} мин: проверьте, что пробуждение по сети "
                    "разрешено в BIOS и ПК подключён к питанию и сети",
                )

        task.status = TaskStatus.failed if failed else TaskStatus.success
        task.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        task = db.get(TaskRun, uuid.UUID(task_run_id))
        if task is not None:
            _append_log(db, task, f"[ERROR] {exc}")
            task.status = TaskStatus.failed
            task.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
