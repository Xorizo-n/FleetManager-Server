import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_roles
from models.user import User, UserRole
from schemas.auth import (
    UserRegister,
    UserOut,
    LoginRequest,
    LoginTotpSetupRequired,
    LoginTotpRequired,
    TokenPair,
    TotpVerifyRequest,
    RefreshRequest,
    TotpResetResponse,
)
from services.audit import record_audit
from services.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from services import totp as totp_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _create_pre_auth_token(user_id: uuid.UUID) -> str:
    from datetime import datetime, timedelta, timezone
    from jose import jwt
    from config import settings

    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "type": "pre_auth", "iat": now, "exp": now + timedelta(minutes=5)}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    existing = db.execute(
        select(User).where((User.username == payload.username) | (User.email == payload.email))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Пользователь с таким именем или email уже существует")

    is_first_user = db.execute(select(User).limit(1)).scalar_one_or_none() is None

    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=UserRole.admin if is_first_user else UserRole.viewer,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    record_audit(db, user.id, "user.register", f"Зарегистрирован пользователь {user.username}")
    return user


@router.post("/login", response_model=LoginTotpSetupRequired | LoginTotpRequired)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")

    pre_auth_token = _create_pre_auth_token(user.id)

    if not user.totp_enabled:
        secret = totp_service.generate_totp_secret()
        user.totp_secret = secret
        db.commit()
        uri = totp_service.get_provisioning_uri(secret, user.username)
        qr = totp_service.generate_qr_code_base64(uri)
        return LoginTotpSetupRequired(pre_auth_token=pre_auth_token, provisioning_uri=uri, qr_code_base64=qr)

    return LoginTotpRequired(pre_auth_token=pre_auth_token)


@router.post("/totp/verify", response_model=TokenPair)
def verify_totp(payload: TotpVerifyRequest, request: Request, db: Session = Depends(get_db)):
    try:
        token_payload = decode_token(payload.pre_auth_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    if token_payload.get("type") != "pre_auth":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Некорректный токен")

    user = db.get(User, uuid.UUID(token_payload["sub"]))
    if user is None or not user.is_active or not user.totp_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден")

    if not totp_service.verify_totp_code(user.totp_secret, payload.code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный код TOTP")

    if not user.totp_enabled:
        user.totp_enabled = True
        db.commit()

    record_audit(db, user.id, "user.login", "Успешный вход с подтверждением TOTP", request)

    return TokenPair(
        access_token=create_access_token(str(user.id), user.role.value),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    try:
        token_payload = decode_token(payload.refresh_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    if token_payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется refresh-токен")

    user = db.get(User, uuid.UUID(token_payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден")

    return TokenPair(
        access_token=create_access_token(str(user.id), user.role.value),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/totp/reset/{user_id}", response_model=TotpResetResponse)
def reset_totp(
    user_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.admin)),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    target.totp_enabled = False
    target.totp_secret = None
    db.commit()
    record_audit(db, admin.id, "user.totp_reset", f"Сброшен TOTP для {target.username}", request)
    return TotpResetResponse(detail="TOTP сброшен, при следующем входе потребуется новая привязка")
