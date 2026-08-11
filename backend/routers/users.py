import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_roles
from models.user import User, UserRole
from schemas.auth import UserOut, UserRoleUpdate
from services.audit import record_audit
from services.permissions import validate_role_change

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    return db.execute(select(User).order_by(User.username)).scalars().all()


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
    target.role = payload.role
    db.commit()
    db.refresh(target)
    record_audit(
        db,
        admin.id,
        "user.role_update",
        f"{target.username}: {old_role.value} -> {target.role.value}",
        request,
    )
    return target
