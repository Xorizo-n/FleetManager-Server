import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_roles
from models.playbook import PlaybookSchedule
from models.user import User, UserRole
from schemas.auth import UserCreate, UserOut, UserRoleUpdate, UserUsage
from services import ldap_users
from services.audit import record_audit
from services.permissions import validate_role_change, validate_user_delete
from services.security import hash_password

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    return db.execute(select(User).order_by(User.username)).scalars().all()


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.admin)),
):
    existing = db.execute(
        select(User).where((User.username == payload.username) | (User.email == payload.email))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким именем или email уже существует",
        )

    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    record_audit(
        db,
        admin.id,
        "user.create",
        f"Создан пользователь {user.username} ({user.role.value})",
        request,
    )
    return user


@router.get("/{user_id}/usage", response_model=UserUsage)
def user_usage(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    """Что изменится при удалении: расписания этого пользователя будут выполняться от учётки
    установки агента, а не от его имени (services/run_as.py)."""
    if db.get(User, user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    schedules = db.execute(select(func.count()).select_from(PlaybookSchedule).where(PlaybookSchedule.owner_id == user_id)).scalar_one()
    return UserUsage(schedules=schedules)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.admin)),
):
    """Удаляет учётную запись. Задачи, журнал аудита, расписания и прочее, что она создала,
    остаются без автора (внешние ключи ON DELETE SET NULL). Доменная запись создастся снова
    при следующем входе, если пользователь всё ещё в группах AD."""
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    active_admins = db.execute(
        select(User).where(User.role == UserRole.admin, User.is_active.is_(True)).with_for_update()
    ).scalars().all()
    db.refresh(target)
    try:
        validate_user_delete(admin.role, admin.id, target.id, target.role, target.is_active, len(active_admins))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    username, role, source = target.username, target.role.value, target.auth_source
    db.delete(target)
    db.commit()
    record_audit(db, admin.id, "user.delete", f"Удалён пользователь {username} ({role}, {source})", request)


@router.patch("/{user_id}/role", response_model=UserOut)
def update_user_role(
    user_id: uuid.UUID,
    payload: UserRoleUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.admin)),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    active_admins = db.execute(
        select(User)
        .where(User.role == UserRole.admin, User.is_active.is_(True))
        .with_for_update()
    ).scalars().all()
    db.refresh(target)
    active_admin_count = len(active_admins)
    try:
        validate_role_change(
            admin.role,
            admin.id,
            target.id,
            target.role,
            payload.role,
            active_admin_count,
            target.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    old_role = target.role
    if target.auth_source == ldap_users.LDAP:
        # Роль доменной записи по умолчанию задают группы AD; ручная остаётся и после входа
        ldap_users.set_manual_role(target, payload.role)
        note = " (вручную)" if target.role_override else " (по группам AD)"
    else:
        target.role = payload.role
        note = ""
    db.commit()
    db.refresh(target)
    record_audit(
        db,
        admin.id,
        "user.role_update",
        f"{target.username}: {old_role.value} -> {target.role.value}{note}",
        request,
    )
    return target
