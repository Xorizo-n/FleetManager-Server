"""Дедупликация хостов: переустановленный ПК занимает свою старую запись, а не плодит новую.

Чистая установка агента сбрасывает machine-id (иначе ПК из одного образа делили бы один id),
поэтому после переустановки ПК регистрируется как новый агент. Раньше сервер занимал только
записи без агента, и у переустановленного ПК появлялась вторая запись, а старая — с историей,
комментарием, группой и задачами — висела офлайн (34 записи после переустановки ПК *-OP 25.10).

Два пути:
* регистрация (`adoptable_host`): новый агент с тем же именем, что у агентской записи, от
  которой давно нет heartbeat, получает эту запись. Если от записи heartbeat приходит, это
  другой ПК с тем же именем (так было с SU5-K118-W07/W09) — тогда, как и раньше, новая запись;
* heartbeat (`absorb_stale_twins`): уже существующие дубли. Живая запись сливается в старую
  запись того же ПК — то же имя и тот же MAC, серийный номер или адрес; данные берутся новые,
  история и ссылки из задач переходят на старую запись, новая удаляется.
"""
import logging
import uuid
from datetime import datetime

from sqlalchemy import String, cast, func, select

from models.agent import AgentAlert, HardwareEvent
from models.credential import Credential
from models.host import Host, HostStatusHistory
from models.playbook import PlaybookSchedule
from models.software import SoftwareHistory, SoftwareItem
from models.task import TaskRun
from models.wallpaper import WallpaperAssignment, WallpaperSchedule
from services.agent_auth import CLONE_GUARD_WINDOW, short_name
from services.audit import record_audit
from services.wake_on_lan import normalize_mac

logger = logging.getLogger(__name__)

# Запись без heartbeat дольше этого — ПК её больше не использует (то же окно, что у защиты от клонов)
STALE_AFTER = CLONE_GUARD_WINDOW

# Заглушки вместо серийного номера: они одинаковы у разных ПК и ничего не доказывают.
# Скриптовый агент писал в серийный номер модель диска — «AirDisk 512GB SSD (477 GB)».
_PLACEHOLDER_SERIALS = {"", "system serial number", "to be filled by o.e.m.", "default string", "none", "0", "123456789"}

# Что не переносится из новой записи в старую
_KEEP_COLUMNS = {"id", "created_at", "updated_at", "comment", "group_id"}


def is_stale(host: Host, now: datetime) -> bool:
    return host.last_seen_at is None or now - host.last_seen_at >= STALE_AFTER


def _real_serial(value: str | None) -> str | None:
    serial = (value or "").strip()
    if serial.lower() in _PLACEHOLDER_SERIALS or serial.endswith("GB)"):
        return None
    return serial


def _macs(host: Host) -> set[str]:
    macs = {normalize_mac(host.hw_mac_address)} if host.hw_mac_address else set()
    for adapter in host.hw_network_adapters or []:
        mac = normalize_mac((adapter or {}).get("mac_address"))
        if mac:
            macs.add(mac)
    macs.discard(None)
    return macs


def same_machine(old: Host, new: Host) -> bool:
    """Тот же ПК: то же имя и совпадает MAC, настоящий серийный номер или адрес."""
    if not old.hostname or not new.hostname or short_name(old.hostname) != short_name(new.hostname):
        return False
    if _macs(old) & _macs(new):
        return True
    serial = _real_serial(old.hw_serial_number)
    if serial and serial == _real_serial(new.hw_serial_number):
        return True
    return bool(old.ip_address) and old.ip_address == new.ip_address


def _namesakes(db, hostname: str, exclude_id: uuid.UUID | None):
    query = select(Host).where(
        Host.is_agent_managed.is_(True),
        Host.agent_id.is_not(None),
        func.lower(func.split_part(Host.hostname, ".", 1)) == short_name(hostname),
    )
    if exclude_id is not None:
        query = query.where(Host.id != exclude_id)
    return db.execute(query).scalars().all()


def adoptable_host(db, hostname: str | None, now: datetime) -> Host | None:
    """Старая агентская запись этого имени, от которой давно нет heartbeat, — для повторной регистрации.

    Если хоть одна запись с этим именем ещё присылает heartbeat, имя занято другим ПК: None."""
    if not hostname:
        return None
    namesakes = _namesakes(db, hostname, None)
    if not namesakes or any(not is_stale(h, now) for h in namesakes):
        return None
    # Из нескольких старых — та, что была на связи последней
    return max(namesakes, key=lambda h: h.last_seen_at or h.created_at)


def reset_for_new_install(host: Host) -> None:
    """Что относится к прошлой установке агента и сбивало бы новую."""
    # Ключи хоста установщик выпускает заново: старые закреплённые ключи отклоняли бы SSH
    host.ssh_state = None
    host.agent_update_target = None


def _replace_id(value, old: str, new: str):
    """Заменяет id в JSON (списки, словари, вложенные), без повторов в списках."""
    if isinstance(value, list):
        out = []
        for item in value:
            item = _replace_id(item, old, new)
            if item not in out:
                out.append(item)
        return out
    if isinstance(value, dict):
        return {(new if k == old else k): _replace_id(v, old, new) for k, v in value.items()}
    return new if value == old else value


def _rewrite_json(db, model, column: str, old: str, new: str) -> int:
    attr = getattr(model, column)
    rows = db.execute(select(model).where(cast(attr, String).like(f"%{old}%"))).scalars().all()
    for row in rows:
        setattr(row, column, _replace_id(getattr(row, column), old, new))
    return len(rows)


def merge_host(db, keep: Host, drop: Host, reason: str) -> Host:
    """Переносит в старую запись `keep` данные и агента новой записи `drop` и удаляет `drop`.

    Остаются: id, дата создания, комментарий (если у новой его нет) и группа, назначенная вручную.
    История статусов, журнал оборудования, алерты и история ПО объединяются, ПО берётся новое,
    ссылки на `drop` в задачах и расписаниях переходят на `keep`."""
    keep_id, drop_id = str(keep.id), str(drop.id)
    old_credential_id = keep.credential_id
    manual_group = keep.group_id if keep.group is not None and not keep.group.is_auto else None
    comment = keep.comment or drop.comment
    values = {c.name: getattr(drop, c.key) for c in Host.__table__.columns if c.name not in _KEEP_COLUMNS}

    # agent_id уникален: сначала снять его с удаляемой записи
    drop.agent_id = None
    drop.agent_token_hash = None
    db.flush()
    for name, value in values.items():
        setattr(keep, name, value)
    keep.comment = comment
    keep.group_id = manual_group or drop.group_id or keep.group_id

    for model in (HostStatusHistory, HardwareEvent, AgentAlert, SoftwareHistory):
        db.query(model).filter(model.host_id == drop.id).update({model.host_id: keep.id}, synchronize_session=False)
    db.query(SoftwareItem).filter(SoftwareItem.host_id == keep.id).delete(synchronize_session=False)
    db.query(SoftwareItem).filter(SoftwareItem.host_id == drop.id).update({SoftwareItem.host_id: keep.id}, synchronize_session=False)
    for assignment in db.query(WallpaperAssignment).filter(WallpaperAssignment.host_id == drop.id).all():
        db.query(WallpaperAssignment).filter(
            WallpaperAssignment.host_id == keep.id, WallpaperAssignment.kind == assignment.kind
        ).delete(synchronize_session=False)
        assignment.host_id = keep.id

    references = sum((
        _rewrite_json(db, TaskRun, "host_ids", drop_id, keep_id),
        _rewrite_json(db, TaskRun, "host_states", drop_id, keep_id),
        _rewrite_json(db, TaskRun, "run_as", drop_id, keep_id),
        _rewrite_json(db, PlaybookSchedule, "host_ids", drop_id, keep_id),
        _rewrite_json(db, WallpaperSchedule, "host_ids", drop_id, keep_id),
    ))
    db.flush()
    db.delete(drop)
    db.flush()

    # Ключ прошлой установки больше нигде не стоит: агентскую учётку без хостов не держим
    if old_credential_id and old_credential_id != keep.credential_id:
        credential = db.get(Credential, old_credential_id)
        if credential is not None and credential.is_agent_managed and not db.query(Host).filter(Host.credential_id == credential.id).count():
            db.delete(credential)
    db.commit()
    record_audit(db, None, "host.merge", f"{keep.hostname}: {drop_id} -> {keep_id} ({reason}); ссылок в задачах: {references}")
    logger.info("Merged host %s (%s) into %s: %s", keep.hostname, drop_id, keep_id, reason)
    return keep


def absorb_stale_twins(db, host: Host, now: datetime) -> Host:
    """Живой хост с heartbeat'ом: если у этого ПК есть старые записи, переезжает в самую старую.

    Возвращает запись, под которой хост живёт дальше."""
    if not host.hostname or not host.is_agent_managed:
        return host
    twins = [t for t in _namesakes(db, host.hostname, host.id) if is_stale(t, now) and same_machine(t, host)]
    if not twins:
        return host
    twins.sort(key=lambda t: t.created_at)
    keep = twins[0]
    keep = merge_host(db, keep, host, "повторная регистрация того же ПК")
    for extra in twins[1:]:
        # Ещё более ранние дубли того же ПК: их история тоже переходит в сохраняемую запись
        _absorb_older(db, keep, extra)
    return keep


def _absorb_older(db, keep: Host, older: Host) -> None:
    """Слить в keep историю ещё одного старого дубля, не трогая данные keep."""
    keep_id, older_id = str(keep.id), str(older.id)
    for model in (HostStatusHistory, HardwareEvent, AgentAlert, SoftwareHistory):
        db.query(model).filter(model.host_id == older.id).update({model.host_id: keep.id}, synchronize_session=False)
    db.query(WallpaperAssignment).filter(WallpaperAssignment.host_id == older.id).delete(synchronize_session=False)
    for model, column in ((TaskRun, "host_ids"), (TaskRun, "host_states"), (TaskRun, "run_as"),
                          (PlaybookSchedule, "host_ids"), (WallpaperSchedule, "host_ids")):
        _rewrite_json(db, model, column, older_id, keep_id)
    keep.comment = keep.comment or older.comment
    credential_id = older.credential_id
    db.delete(older)
    db.flush()
    if credential_id and credential_id != keep.credential_id:
        credential = db.get(Credential, credential_id)
        if credential is not None and credential.is_agent_managed and not db.query(Host).filter(Host.credential_id == credential.id).count():
            db.delete(credential)
    db.commit()
    record_audit(db, None, "host.merge", f"{keep.hostname}: {older_id} -> {keep_id} (ещё один старый дубль)")
