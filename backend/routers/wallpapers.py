import base64
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_roles
from models.host import Host, HostGroup
from models.user import User, UserRole
from models.wallpaper import ObservedWallpaper, Wallpaper, WallpaperAssignment, WallpaperSchedule
from schemas.wallpaper import (
    ObservedWallpaperOut,
    WallpaperAssignmentOut,
    WallpaperAssignRequest,
    WallpaperAssignResult,
    WallpaperOut,
    WallpaperRename,
    WallpaperScheduleOut,
)
from services.audit import record_audit
from services.wallpapers import (
    MAX_UPLOAD_BYTES,
    WallpaperError,
    apply_assignment,
    perceptual_hash,
    remove_file,
    store_upload,
    wallpaper_path,
)

router = APIRouter(prefix="/wallpapers", tags=["wallpapers"])

EDITOR_ROLES = (UserRole.admin, UserRole.operator)


def _out(wallpaper: Wallpaper) -> WallpaperOut:
    out = WallpaperOut.model_validate(wallpaper)
    out.thumbnail_base64 = base64.b64encode(wallpaper.thumbnail).decode()
    out.phash = perceptual_hash(wallpaper.sha256, wallpaper.thumbnail)
    return out


@router.get("", response_model=list[WallpaperOut])
def list_wallpapers(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return [_out(w) for w in db.execute(select(Wallpaper).order_by(Wallpaper.created_at.desc())).scalars()]


@router.post("", response_model=WallpaperOut, status_code=status.HTTP_201_CREATED)
async def upload_wallpaper(
    request: Request,
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
):
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        wallpaper = store_upload(db, data, name, file.filename, user.id)
        db.commit()
    except WallpaperError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.refresh(wallpaper)
    record_audit(db, user.id, "wallpaper.upload", f"{wallpaper.name} {wallpaper.sha256[:12]}", request)
    return _out(wallpaper)


@router.patch("/{wallpaper_id}", response_model=WallpaperOut)
def rename_wallpaper(wallpaper_id: uuid.UUID, payload: WallpaperRename, db: Session = Depends(get_db), _: User = Depends(require_roles(*EDITOR_ROLES))):
    wallpaper = db.get(Wallpaper, wallpaper_id)
    if wallpaper is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Изображение не найдено")
    wallpaper.name = payload.name.strip()
    db.commit()
    return _out(wallpaper)


@router.delete("/{wallpaper_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_wallpaper(wallpaper_id: uuid.UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(*EDITOR_ROLES))):
    wallpaper = db.get(Wallpaper, wallpaper_id)
    if wallpaper is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Изображение не найдено")
    used = db.execute(select(WallpaperAssignment.id).where(WallpaperAssignment.wallpaper_id == wallpaper_id).limit(1)).first()
    pending = db.execute(select(WallpaperSchedule).where(WallpaperSchedule.status == "pending")).scalars().all()
    if used or any(str(wallpaper_id) in (s.desktop, s.lock_screen) for s in pending):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Изображение назначено ПК или группе либо стоит в расписании — сначала снимите назначение")
    remove_file(wallpaper)
    db.delete(wallpaper)
    db.commit()
    record_audit(db, user.id, "wallpaper.delete", wallpaper.name, request)


@router.get("/{wallpaper_id}/image")
def wallpaper_image(wallpaper_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    wallpaper = db.get(Wallpaper, wallpaper_id)
    if wallpaper is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Изображение не найдено")
    return FileResponse(wallpaper_path(wallpaper), media_type=wallpaper.content_type)


@router.get("/observed", response_model=list[ObservedWallpaperOut])
def observed_wallpapers(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Миниатюры обоев не из каталога, которые стоят на ПК (обои образа и т. п.)."""
    return [
        ObservedWallpaperOut(sha256=o.sha256, path=o.path, thumbnail_base64=base64.b64encode(o.thumbnail).decode(),
                             phash=perceptual_hash(o.sha256, o.thumbnail))
        for o in db.execute(select(ObservedWallpaper)).scalars()
    ]


@router.get("/assignments", response_model=list[WallpaperAssignmentOut])
def list_assignments(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.execute(select(WallpaperAssignment)).scalars().all()


@router.post("/assign", response_model=WallpaperAssignResult)
def assign_wallpapers(payload: WallpaperAssignRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(*EDITOR_ROLES))):
    if not payload.host_ids and not payload.group_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Не выбраны ПК")
    if payload.desktop is None and payload.lock_screen is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Не выбраны обои")
    found_hosts = set(db.execute(select(Host.id).where(Host.id.in_(payload.host_ids))).scalars()) if payload.host_ids else set()
    found_groups = set(db.execute(select(HostGroup.id).where(HostGroup.id.in_(payload.group_ids))).scalars()) if payload.group_ids else set()
    if len(found_hosts) != len(set(payload.host_ids)) or len(found_groups) != len(set(payload.group_ids)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Часть ПК или групп не найдена")
    for value in (payload.desktop, payload.lock_screen):
        if value not in (None, "clear") and db.get(Wallpaper, uuid.UUID(value)) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Изображение не найдено в каталоге")

    targets = f"hosts={len(found_hosts)} groups={len(found_groups)} desktop={payload.desktop} lock={payload.lock_screen}"
    if payload.apply_at is not None and payload.apply_at > datetime.now(timezone.utc):
        schedule = WallpaperSchedule(
            apply_at=payload.apply_at, host_ids=[str(h) for h in payload.host_ids], group_ids=[str(g) for g in payload.group_ids],
            desktop=payload.desktop, lock_screen=payload.lock_screen, comment=payload.comment, created_by=user.id,
        )
        db.add(schedule)
        db.commit()
        record_audit(db, user.id, "wallpaper.schedule", f"{payload.apply_at.isoformat()} {targets}", request)
        return WallpaperAssignResult(schedule_id=schedule.id)
    try:
        changed = apply_assignment(db, payload.host_ids, payload.group_ids, payload.desktop, payload.lock_screen, user.id)
        db.commit()
    except WallpaperError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit(db, user.id, "wallpaper.assign", targets, request)
    return WallpaperAssignResult(changed=changed)


@router.get("/schedules", response_model=list[WallpaperScheduleOut])
def list_schedules(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.execute(
        select(WallpaperSchedule, User.username).outerjoin(User, User.id == WallpaperSchedule.created_by)
        .order_by(WallpaperSchedule.apply_at.desc()).limit(200)
    ).all()
    return [WallpaperScheduleOut.model_validate(s).model_copy(update={"created_by_name": name}) for s, name in rows]


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_schedule(schedule_id: uuid.UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(*EDITOR_ROLES))):
    schedule = db.get(WallpaperSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Расписание не найдено")
    if schedule.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Смена уже выполнена или отменена")
    schedule.status = "cancelled"
    db.commit()
    record_audit(db, user.id, "wallpaper.schedule.cancel", str(schedule_id), request)
