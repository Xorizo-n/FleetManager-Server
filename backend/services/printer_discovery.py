"""Discover printers through one online Windows PC per named room."""
import ipaddress
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import redis
from sqlalchemy.exc import IntegrityError
from celery_app import celery_app
from config import settings
from database import SessionLocal
from models.host import Host, HostStatus
from models.printer import Printer
from services.ansible_runner import build_full_inventory, run_ansible
from services.crypto import encrypt_secret
from services.host_grouping import parse_host_name
from services.ssh_health import ssh_blocked_reason
from services.inventory_generator import host_group_credential
from services.printer_monitor import poll_printer

logger = logging.getLogger(__name__)
LOCK_KEY = "printer-discovery:lock"
STATUS_KEY = "printer-discovery:status"
TTL = 7200


def store():
    return redis.Redis.from_url(settings.celery_broker_url, decode_responses=True)


def save_status(client, data):
    client.set(STATUS_KEY, json.dumps(data, ensure_ascii=False), ex=TTL * 12)


def discovery_status():
    client = store()
    value = client.get(STATUS_KEY)
    if not value: return {"status": "never"}
    result = json.loads(value)
    if result.get("status") in ("queued", "running") and not client.exists(LOCK_KEY):
        result["status"] = "interrupted"
    return result


def enqueue_discovery():
    client = store()
    token = uuid.uuid4().hex
    if not client.set(LOCK_KEY, token, nx=True, ex=TTL): return False
    try:
        save_status(client, {"status": "queued", "started_at": None})
        discover_printers.delay(token)
    except Exception:
        client.delete(LOCK_KEY)
        save_status(client, {"status": "failed", "message": "Не удалось поставить поиск в очередь"})
        raise
    return True


def script_command():
    # Ansible's PowerShell shell encodes raw commands itself. Avoid encoding twice:
    # the nested command would exceed Windows' command-line length limit.
    return Path(__file__).with_name("printer_discovery.ps1").read_text(encoding="utf-8-sig")


def select_hosts(hosts):
    """Order all room PCs, preferring online hosts with usable SSH credentials.

    Rooms without an online host are omitted, as in the scheduled discovery contract.
    A stale offline/unknown status must not prevent trying a fallback in an eligible room.
    """
    rooms = {}
    for host in hosts:
        parts = parse_host_name(host.hostname)
        if parts is None: continue
        rooms.setdefault(parts.room_group, []).append(host)
    return {room: sorted(candidates, key=lambda h: (
                getattr(h, "status", HostStatus.online) != HostStatus.online,
                bool(ssh_blocked_reason(getattr(h, "ssh_state", None))),
                not bool(getattr(h, "credential_id", None) or (host_group_credential(h) if getattr(h, "group_id", None) else None)),
                -(h.last_seen_at.timestamp() if h.last_seen_at else 0), str(h.id)))
            for room, candidates in rooms.items()
            if any(getattr(h, "status", HostStatus.online) == HostStatus.online for h in candidates)}


def parse_result(stdout):
    marker = "FM_PRINTER_DISCOVERY="
    line = next((line for line in stdout.splitlines() if line.startswith(marker)), None)
    if not line: raise ValueError("ПК не вернул результат поиска")
    result = json.loads(line[len(marker):])
    if not isinstance(result, dict) or "subnet" not in result: raise ValueError("Нет подсети")
    subnet = ipaddress.ip_network(result["subnet"], strict=True)
    if subnet.version != 4 or subnet.prefixlen < 24: raise ValueError("Некорректная подсеть")
    printers = []
    for item in result.get("printers", []):
        ip = ipaddress.IPv4Address(item["address"])
        if ip not in subnet or ip.is_loopback or ip.is_multicast or ip.is_unspecified or ip.is_link_local or ip.is_reserved: continue
        name = str(item.get("name") or "").strip()[:128]
        model = str(item.get("model") or "").strip()[:128]
        printers.append({"address": str(ip), "name": name, "model": model})
    return str(subnet), printers


def add_results(db, findings):
    """Never overwrite manual edits or reassign an already registered address."""
    added = []
    for address, reports in findings.items():
        if db.query(Printer.id).filter(Printer.address == address).first(): continue
        item = reports[0][1]
        parts = parse_host_name(item["name"])
        rooms = sorted({room for room, _ in reports})
        if parts:
            location = parts.room_group
        elif len(rooms) == 1:
            location = f"{rooms[0]} (найден рядом, уточнить)"
        else:
            location = "Найден из нескольких аудиторий — уточнить"
        printer = Printer(name=item["name"] or item["model"] or address, address=address,
                          location=location, community_encrypted=encrypt_secret("public"))
        try:
            # A concurrent manual addition or discovery wins without aborting other results.
            with db.begin_nested():
                db.add(printer); db.flush()
            db.commit()
        except IntegrityError:
            db.rollback(); continue
        added.append(str(printer.id))
    return added


@celery_app.task(name="services.printer_discovery.discover_printers")
def discover_printers(token):
    client = store()
    if client.get(LOCK_KEY) != token: return
    started = datetime.now(timezone.utc).isoformat()
    status = {"status": "running", "started_at": started}
    save_status(client, status)
    try:
        with SessionLocal() as db:
            rooms = select_hosts(db.query(Host).all())
            # Store IDs only: do not hold database connections while scanning the network.
            remaining = {room: [host.id for host in hosts] for room, hosts in rooms.items()}
        findings = {}
        successful = set()
        command = script_command()
        while remaining:
            # Run at most one PC per room in each round; failed rooms advance to the next PC.
            attempts = {room: ids.pop(0) for room, ids in remaining.items()}
            room_by_host = {str(host_id): room for room, host_id in attempts.items()}
            with SessionLocal() as db:
                inventory = build_full_inventory(db, list(attempts.values()))
            completed = set()
            try:
                result = run_ansible(module="ansible.builtin.raw", module_args=command, host_pattern="all",
                                     inventory=inventory, quiet=True, timeout=3600, envvars={"ANSIBLE_FORKS": "4"})
                for event in result.events:
                    info = event.get("event_data", {}); host_id = info.get("host")
                    if host_id not in room_by_host: continue
                    if event.get("event") == "runner_on_ok" and (info.get("res") or {}).get("rc", 1) == 0:
                        try:
                            _, printers = parse_result((info.get("res") or {}).get("stdout") or "")
                            room = room_by_host[host_id]
                            completed.add(room)
                            for printer in printers: findings.setdefault(printer["address"], []).append((room, printer))
                        except (ValueError, TypeError, KeyError):
                            logger.warning("Printer discovery returned invalid output from %s", host_id)
            except Exception:
                logger.exception("Printer discovery round failed; trying remaining PCs")
            successful.update(completed)
            remaining = {room: ids for room, ids in remaining.items() if room not in completed and ids}
            # Long retries must keep their lock; never overwrite another discovery's lock.
            if not client.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('expire',KEYS[1],ARGV[2]) else return 0 end", 1, LOCK_KEY, token, TTL):
                logger.warning("Printer discovery lock lost; aborting")
                return
        with SessionLocal() as db: added = add_results(db, findings)
        for printer_id in added:
            try: poll_printer.delay(printer_id)
            except Exception: logger.exception("Could not queue printer poll: %s", printer_id)
        status.update(status="completed", finished_at=datetime.now(timezone.utc).isoformat(),
                      rooms_total=len(rooms), rooms_scanned=len(successful), found=len(findings), added=len(added),
                      failed_rooms=sorted(set(rooms) - successful))
    except Exception:
        logger.exception("Printer discovery failed")
        status.update(status="failed", finished_at=datetime.now(timezone.utc).isoformat(), message="Ошибка поиска; подробности в журнале Celery")
    finally:
        if client.get(LOCK_KEY) == token: save_status(client, status)
        client.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end", 1, LOCK_KEY, token)


@celery_app.task(name="services.printer_discovery.schedule_discovery")
def schedule_discovery():
    enqueue_discovery()
