"""Read-only SNMP polling. A missing response means unknown reachability, not a printer fault."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
import redis
from pysnmp.hlapi.v3arch.asyncio import (CommunityData, ContextData, ObjectIdentity, ObjectType,
    SnmpEngine, UdpTransportTarget, get_cmd, next_cmd, walk_cmd)
from celery_app import celery_app
from config import settings
from database import SessionLocal
from models.printer import Printer
from services.crypto import decrypt_secret

logger = logging.getLogger(__name__)


def text_value(value):
    try:
        return value.asOctets().decode("utf-8", errors="replace").strip("\x00 ")
    except (AttributeError, TypeError):
        return value.prettyPrint()


def supply_items(rows):
    """Join the Printer MIB supply columns by their full row index."""
    result = []
    for row in rows.values():
        if 6 not in row: continue
        try:
            maximum, level = int(row.get(8, -1)), int(row.get(9, -1))
        except (TypeError, ValueError):
            maximum, level = -1, -1
        percent = round(level * 100 / maximum) if maximum > 0 and 0 <= level <= maximum else None
        result.append({"name": row[6], "percent": percent})
    return result


async def read_printer(address, community):
    engine = SnmpEngine()
    try:
        target = await UdpTransportTarget.create((address, 161), timeout=1.5, retries=0)
        auth = CommunityData(community, mpModel=1)
        async def get(oid, required=False):
            err, status, _, values = await get_cmd(engine, auth, target, ContextData(), ObjectType(ObjectIdentity(oid)))
            if err or status:
                if required: raise RuntimeError("SNMP не ответил")
                return None
            value = values[0][1]
            if value.__class__.__name__ in ("NoSuchObject", "NoSuchInstance", "EndOfMibView"): return None
            return value
        async def first_under(root):
            """Find the first table row without assuming a vendor's device index."""
            err, status, _, values = await next_cmd(engine, auth, target, ContextData(), ObjectType(ObjectIdentity(root)))
            if err or status or not values: return None, None
            oid, value = values[0]
            prefix = tuple(int(x) for x in root.split('.'))
            parts = oid.getOid().asTuple()
            if parts[:len(prefix)] != prefix or len(parts) != len(prefix) + 1:
                return None, None
            if value.__class__.__name__ in ("NoSuchObject", "NoSuchInstance", "EndOfMibView"):
                return None, None
            return parts[-1], value
        async def walk(root, limit=120):
            result = {}
            async for err, status, _, values in walk_cmd(engine, auth, target, ContextData(), ObjectType(ObjectIdentity(root)), lexicographicMode=False):
                if err or status: break
                for oid, value in values:
                    parts = oid.getOid().asTuple(); prefix = tuple(int(x) for x in root.split('.'))
                    suffix = parts[len(prefix):]
                    if len(suffix) < 2: continue
                    result.setdefault(suffix[1:], {})[suffix[0]] = text_value(value)
                if sum(len(x) for x in result.values()) >= limit: break
            return result
        name = await get("1.3.6.1.2.1.1.5.0", required=True)
        if name is None: raise RuntimeError("Нет ответа SNMP")
        device_index, state = await first_under("1.3.6.1.2.1.25.3.5.1.1")
        model = await get(f"1.3.6.1.2.1.25.3.2.1.3.{device_index}") if device_index else None
        errors = await get(f"1.3.6.1.2.1.25.3.5.1.2.{device_index}") if device_index else None
        _, pages = await first_under(f"1.3.6.1.2.1.43.10.2.1.4.{device_index}") if device_index else (None, None)
        supplies = await walk("1.3.6.1.2.1.43.11.1.1")
        alerts = await walk("1.3.6.1.2.1.43.18.1.1")
        try: count = int(pages) if pages is not None and int(pages) >= 0 else None
        except (ValueError, TypeError): count = None
        try: state_number = int(state) if state is not None else None
        except (ValueError, TypeError): state_number = None
        error_names = ["Мало бумаги", "Нет бумаги", "Мало тонера", "Нет тонера", "Открыта крышка", "Замятие бумаги", "Не в сети", "Требуется обслуживание", "Нет входного лотка", "Нет выходного лотка", "Нет расходника", "Выходной лоток почти заполнен", "Выходной лоток заполнен", "Входной лоток пуст", "Требуется профилактика"]
        try: bits = errors.asOctets() if errors is not None else b""
        except AttributeError: bits = b""
        problems = [label for i, label in enumerate(error_names) if i // 8 < len(bits) and bits[i // 8] & (0x80 >> (i % 8))]
        messages = [{"severity": row.get(2), "message": row.get(8)} for row in alerts.values() if row.get(8)]
        return {"sys_name": text_value(name), "model": text_value(model) if model is not None else None,
                "printer_state": state_number, "problems": problems, "pages": count,
                "supplies": supply_items(supplies), "alerts": messages}
    finally:
        engine.close_dispatcher()


@celery_app.task(name="services.printer_monitor.poll_printer")
def poll_printer(printer_id):
    lock = redis.Redis.from_url(settings.celery_broker_url).lock(f"printer-poll:{printer_id}", timeout=180, blocking_timeout=0)
    if not lock.acquire(blocking=False): return
    try:
        with SessionLocal() as db:
            printer = db.get(Printer, uuid.UUID(printer_id))
            if not printer: return
            address, encrypted = printer.address, printer.community_encrypted
        try:
            data = asyncio.run(asyncio.wait_for(read_printer(address, decrypt_secret(encrypted)), timeout=90))
            ok = True
        except Exception:
            logger.info("SNMP poll failed for printer %s", printer_id, exc_info=True)
            data, ok = None, False
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            printer = db.get(Printer, uuid.UUID(printer_id))
            if not printer or printer.address != address or printer.community_encrypted != encrypted: return
            printer.status = "online" if ok else "unreachable"
            printer.last_checked_at = now
            if ok:
                printer.last_seen_at = now; printer.data = data
            db.commit()
    finally:
        try: lock.release()
        except redis.exceptions.LockError: pass


@celery_app.task(name="services.printer_monitor.schedule_printers")
def schedule_printers():
    with SessionLocal() as db:
        ids = [str(row[0]) for row in db.query(Printer.id).all()]
    for printer_id in ids: poll_printer.delay(printer_id)
