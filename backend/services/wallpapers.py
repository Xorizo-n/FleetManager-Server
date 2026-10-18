"""Обои рабочего стола и экрана блокировки.

Каталог изображений хранится на сервере (settings.wallpaper_dir, в БД — метаданные и миниатюра).
Назначение делается ПК или группе: у ПК действует своё, иначе — ближайшей группы вверх по дереву.
Ничего не назначено — обоями сервер не управляет, и агент возвращает то, что было в образе.

Агент (2026.10.18+) получает назначенные обои в ответе на heartbeat, сам скачивает изображение
своим токеном и ставит его через локальную групповую политику (там же их задаёт образ), а в
heartbeat сообщает, что стоит на самом деле. Смена в заданное время — WallpaperSchedule:
в apply_at назначения применяются так же, как «сейчас» (apply_due_schedules, раз в минуту).
"""

import base64
import hashlib
import io
import logging
import os
import uuid
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from celery_app import celery_app
from config import settings
from database import SessionLocal
from models.host import Host, HostGroup
from models.wallpaper import DESKTOP, LOCK_SCREEN, WALLPAPER_KINDS, ObservedWallpaper, Wallpaper, WallpaperAssignment, WallpaperSchedule

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 30 * 1024 * 1024
THUMBNAIL_WIDTH = 320
# Форматы, которые Windows берёт и для обоев, и для экрана блокировки
FORMATS = {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"), "BMP": ("image/bmp", ".bmp")}
CLEAR = "clear"
# WallpaperStyle: заполнение — экран без полос при любом соотношении сторон
DEFAULT_STYLE = "4"


class WallpaperError(ValueError):
    pass


def wallpaper_dir() -> str:
    return settings.wallpaper_dir


def wallpaper_path(wallpaper: Wallpaper) -> str:
    return os.path.join(wallpaper_dir(), wallpaper.file_name)


def make_thumbnail(image) -> bytes:
    from PIL import Image

    thumb = image.convert("RGB")
    width = min(THUMBNAIL_WIDTH, thumb.width)
    height = max(1, round(thumb.height * width / thumb.width))
    thumb = thumb.resize((width, height), Image.LANCZOS)
    out = io.BytesIO()
    thumb.save(out, "JPEG", quality=80)
    return out.getvalue()


@lru_cache(maxsize=4096)
def perceptual_hash(sha256: str, thumbnail: bytes) -> str | None:
    """dHash миниатюры: 64 бита, 16 hex-символов. Одна картинка, сохранённая заново (другое
    сжатие или разрешение), даёт другой SHA-256, но почти тот же dHash. Так, urfu-desktop.jpg
    создаётся отдельно в профиле каждого пользователя под его экран: варианты отличаются
    на 1–7 бит, а разные обои — на 21 и больше. По нему страница «Обои» объединяет варианты
    в одну плитку. sha256 — ключ кэша: миниатюра для хэша не меняется."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(thumbnail)) as image:
            gray = image.convert("L").resize((9, 8), Image.LANCZOS)
            pixels = gray.tobytes()
    except Exception:  # noqa: BLE001 — битая миниатюра просто не группируется
        return None
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (pixels[row * 9 + col] > pixels[row * 9 + col + 1])
    return f"{bits:016x}"


def inspect_image(data: bytes) -> tuple[str, str, int, int, bytes]:
    """(content_type, расширение, ширина, высота, миниатюра); WallpaperError — не изображение или формат не тот."""
    from PIL import Image, UnidentifiedImageError

    if not data:
        raise WallpaperError("Пустой файл")
    if len(data) > MAX_UPLOAD_BYTES:
        raise WallpaperError(f"Файл больше {MAX_UPLOAD_BYTES // 1024 // 1024} МБ")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise WallpaperError("Это не изображение или файл повреждён") from exc
    if image.format not in FORMATS:
        raise WallpaperError("Подходят JPEG, PNG и BMP")
    content_type, ext = FORMATS[image.format]
    return content_type, ext, image.width, image.height, make_thumbnail(image)


def store_upload(db: Session, data: bytes, name: str | None, original_name: str | None, user_id) -> Wallpaper:
    content_type, ext, width, height, thumbnail = inspect_image(data)
    sha = hashlib.sha256(data).hexdigest()
    existing = db.execute(select(Wallpaper).where(Wallpaper.sha256 == sha)).scalar_one_or_none()
    if existing is not None:
        raise WallpaperError(f"Это изображение уже есть в каталоге: «{existing.name}»")
    os.makedirs(wallpaper_dir(), exist_ok=True)
    file_name = sha + ext
    path = os.path.join(wallpaper_dir(), file_name)
    temp = path + ".upload"
    with open(temp, "wb") as f:
        f.write(data)
    os.replace(temp, path)
    title = (name or "").strip() or os.path.splitext(os.path.basename(original_name or ""))[0].strip() or sha[:12]
    wallpaper = Wallpaper(
        name=title[:128], original_name=(original_name or None) and original_name[:255], file_name=file_name,
        content_type=content_type, sha256=sha, size_bytes=len(data), width=width, height=height,
        thumbnail=thumbnail, created_by=user_id,
    )
    db.add(wallpaper)
    return wallpaper


def remove_file(wallpaper: Wallpaper) -> None:
    try:
        os.remove(wallpaper_path(wallpaper))
    except FileNotFoundError:
        pass


# ---------- назначения ----------

def effective_wallpapers(host: Host, assignments: list[WallpaperAssignment], groups: dict) -> dict[str, Wallpaper | None]:
    """Обои, которые должны стоять на ПК: своё назначение, иначе ближайшей группы вверх по дереву."""
    by_host = {a.kind: a for a in assignments if a.host_id == host.id}
    by_group: dict[tuple, WallpaperAssignment] = {(a.group_id, a.kind): a for a in assignments if a.group_id is not None}
    result: dict[str, Wallpaper | None] = {}
    for kind in WALLPAPER_KINDS:
        found = by_host.get(kind)
        group_id, seen = host.group_id, set()
        while found is None and group_id is not None and group_id not in seen:
            seen.add(group_id)
            found = by_group.get((group_id, kind))
            group = groups.get(group_id)
            group_id = group.parent_id if group is not None else None
        result[kind] = found.wallpaper if found is not None else None
    return result


def host_effective_wallpapers(db: Session, host: Host) -> dict[str, Wallpaper | None]:
    group_chain: dict = {}
    group_id = host.group_id
    while group_id is not None and group_id not in group_chain:
        group = db.get(HostGroup, group_id)
        if group is None:
            break
        group_chain[group_id] = group
        group_id = group.parent_id
    conditions = [WallpaperAssignment.host_id == host.id]
    if group_chain:
        conditions.append(WallpaperAssignment.group_id.in_(list(group_chain)))
    from sqlalchemy import or_

    assignments = db.execute(select(WallpaperAssignment).where(or_(*conditions))).scalars().all()
    return effective_wallpapers(host, list(assignments), group_chain)


def group_subtree(db: Session, group_id) -> tuple[set, set]:
    """Подгруппы группы (без неё самой) и все ПК поддерева, включая ПК самой группы."""
    children: dict = {}
    for gid, parent_id in db.execute(select(HostGroup.id, HostGroup.parent_id)).all():
        children.setdefault(parent_id, []).append(gid)
    descendants, stack = set(), list(children.get(group_id, []))
    while stack:
        gid = stack.pop()
        if gid in descendants:
            continue
        descendants.add(gid)
        stack.extend(children.get(gid, []))
    hosts = set(db.execute(select(Host.id).where(Host.group_id.in_(descendants | {group_id}))).scalars())
    return descendants, hosts


def narrower_assignments(db: Session, group_id, kind: str) -> list[WallpaperAssignment]:
    """Назначения вида kind у подгрупп и ПК внутри группы — их перекрыло бы назначение группы."""
    descendants, hosts = group_subtree(db, group_id)
    if not descendants and not hosts:
        return []
    from sqlalchemy import or_

    conditions = []
    if descendants:
        conditions.append(WallpaperAssignment.group_id.in_(descendants))
    if hosts:
        conditions.append(WallpaperAssignment.host_id.in_(hosts))
    return list(db.execute(select(WallpaperAssignment).where(WallpaperAssignment.kind == kind, or_(*conditions))).scalars())


def apply_assignment(db: Session, host_ids: list, group_ids: list, desktop: str | None, lock_screen: str | None, user_id) -> int:
    """Ставит или снимает назначения. desktop/lock_screen: id обоев, CLEAR — снять, None — не менять.
    Возвращает число изменённых назначений.

    Назначение или снятие у группы действует на всю группу: назначения того же вида у её
    аудиторий и ПК внутри снимаются. Иначе «обои на весь SU5» не доходили до аудиторий, которым
    раньше назначили свои, — у ПК действует ближайшее назначение. Группы обрабатываются раньше
    отдельных ПК, поэтому ПК, выбранный в том же запросе отдельно, получает своё назначение."""
    changed = 0
    targets = [("group", uuid.UUID(str(g))) for g in group_ids] + [("host", uuid.UUID(str(h))) for h in host_ids]
    for kind, value in ((DESKTOP, desktop), (LOCK_SCREEN, lock_screen)):
        if value is None:
            continue
        wallpaper_id = None if value == CLEAR else uuid.UUID(str(value))
        if wallpaper_id is not None and db.get(Wallpaper, wallpaper_id) is None:
            raise WallpaperError("Изображение удалено из каталога")
        for target_type, target_id in targets:
            if target_type == "group":
                for narrower in narrower_assignments(db, target_id, kind):
                    db.delete(narrower)
                    changed += 1
                db.flush()
            column = WallpaperAssignment.host_id if target_type == "host" else WallpaperAssignment.group_id
            existing = db.execute(select(WallpaperAssignment).where(column == target_id, WallpaperAssignment.kind == kind)).scalar_one_or_none()
            if wallpaper_id is None:
                if existing is not None:
                    db.delete(existing)
                    changed += 1
            elif existing is None:
                db.add(WallpaperAssignment(
                    host_id=target_id if target_type == "host" else None,
                    group_id=target_id if target_type == "group" else None,
                    kind=kind, wallpaper_id=wallpaper_id, created_by=user_id,
                ))
                changed += 1
            elif existing.wallpaper_id != wallpaper_id:
                existing.wallpaper_id = wallpaper_id
                existing.created_by = user_id
                changed += 1
    return changed


def apply_due_schedules(db: Session, now: datetime | None = None) -> int:
    """Применяет запланированные смены, чьё время пришло."""
    now = now or datetime.now(timezone.utc)
    due = db.execute(
        select(WallpaperSchedule).where(WallpaperSchedule.status == "pending", WallpaperSchedule.apply_at <= now).order_by(WallpaperSchedule.apply_at)
    ).scalars().all()
    for schedule in due:
        try:
            with db.begin_nested():
                hosts = [h for h in schedule.host_ids if db.get(Host, uuid.UUID(str(h))) is not None]
                groups = [g for g in schedule.group_ids if db.get(HostGroup, uuid.UUID(str(g))) is not None]
                changed = apply_assignment(db, hosts, groups, schedule.desktop, schedule.lock_screen, schedule.created_by)
            schedule.status = "applied"
            schedule.result = f"Изменено назначений: {changed}"
        except WallpaperError as exc:
            schedule.status = "failed"
            schedule.result = str(exc)
        schedule.applied_at = now
    db.commit()
    return len(due)


# ---------- обмен с агентом ----------

def wallpaper_target(wallpaper: Wallpaper | None) -> dict | None:
    if wallpaper is None:
        return None
    return {"id": str(wallpaper.id), "sha256": wallpaper.sha256, "file_name": wallpaper.file_name, "style": DEFAULT_STYLE}


def heartbeat_wallpaper(db: Session, host: Host) -> dict:
    """Часть ответа на heartbeat: что должно стоять и миниатюры каких текущих обоев нужны серверу."""
    effective = host_effective_wallpapers(db, host)
    wanted = []
    state = host.wallpaper_state or {}
    shas = {(state.get(kind) or {}).get("sha256") for kind in WALLPAPER_KINDS} - {None}
    if shas:
        known = set(db.execute(select(Wallpaper.sha256).where(Wallpaper.sha256.in_(shas))).scalars())
        known |= set(db.execute(select(ObservedWallpaper.sha256).where(ObservedWallpaper.sha256.in_(shas))).scalars())
        wanted = sorted(shas - known)
    return {"desktop": wallpaper_target(effective[DESKTOP]), "lock_screen": wallpaper_target(effective[LOCK_SCREEN]), "thumbnails": wanted}


def store_report(db: Session, host: Host, report, now: datetime) -> None:
    """Запоминает, что стоит на ПК, и миниатюры обоев не из каталога."""
    data = report.model_dump(mode="json", exclude={"thumbnails"})
    data["reported_at"] = now.isoformat()
    host.wallpaper_state = data
    for thumb in report.thumbnails:
        if db.get(ObservedWallpaper, thumb.sha256) is not None or db.execute(select(Wallpaper.id).where(Wallpaper.sha256 == thumb.sha256)).first():
            continue
        try:
            raw = base64.b64decode(thumb.jpeg_base64, validate=True)
            from PIL import Image

            with Image.open(io.BytesIO(raw)) as image:
                image.verify()
        except Exception:  # noqa: BLE001 — чужие данные: битая миниатюра просто не сохраняется
            logger.warning("Bad wallpaper thumbnail from %s", host.hostname)
            continue
        path = next((c.path for c in (report.desktop, report.lock_screen) if c is not None and c.sha256 == thumb.sha256), None)
        db.add(ObservedWallpaper(sha256=thumb.sha256, path=path, thumbnail=raw))


@celery_app.task(name="services.wallpapers.apply_wallpaper_schedules")
def apply_wallpaper_schedules() -> int:
    db = SessionLocal()
    try:
        return apply_due_schedules(db)
    finally:
        db.close()
