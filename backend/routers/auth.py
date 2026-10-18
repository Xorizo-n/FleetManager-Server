import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
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
    ChangePasswordRequest,
)
from services.audit import record_audit
from services.rate_limiter import check_rate_limit
from services.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from services import ldap_auth, ldap_config, ldap_users
from services import totp as totp_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _create_pre_auth_token(user_id: uuid.UUID) -> str:
    from datetime import datetime, timedelta, timezone
    from jose import jwt
    from config import settings

    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "type": "pre_auth", "iat": now, "exp": now + timedelta(minutes=5)}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# SEC-01: Registration is open only during bootstrap (no users in DB).
# Once any user exists, only admins can create new accounts.
@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, request: Request, db: Session = Depends(get_db)):
    is_first_user = db.execute(select(User).limit(1)).scalar_one_or_none() is None

    if not is_first_user:
        # Require admin token for all subsequent registrations
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Регистрация закрыта. Новых пользователей создаёт администратор.",
            )
        try:
            token_data = decode_token(auth_header[7:])
            registrar = db.get(User, uuid.UUID(token_data["sub"]))
            if registrar is None or not registrar.is_active or registrar.role != UserRole.admin:
                raise ValueError("not admin")
        except (ValueError, KeyError):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Регистрация закрыта. Новых пользователей создаёт администратор.",
            )

    existing = db.execute(
        select(User).where((User.username == payload.username) | (User.email == payload.email))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Пользователь с таким именем или email уже существует")

    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=UserRole.admin if is_first_user else UserRole.viewer,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    record_audit(db, user.id, "user.register", f"Зарегистрирован пользователь {user.username}", request)
    return user


# SEC-02: Rate limiting — 10 login attempts per IP per minute.
@router.post("/login", response_model=TokenPair | LoginTotpSetupRequired | LoginTotpRequired)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    if check_rate_limit(f"login:{ip}", limit=10, window_seconds=60):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Слишком много попыток. Повторите через минуту.")

    user = ldap_users.find_local(db, payload.username)
    if user is None and ldap_auth.enabled():
        user = _ldap_login(db, payload, request)
    elif user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")

    # Отладочный режим платформы: второй фактор выключен настройкой TOTP_REQUIRED.
    # Пароль по-прежнему проверяется, вход фиксируется в аудите отдельным событием.
    if not settings.totp_required:
        record_audit(db, user.id, "user.login", "Вход без TOTP: второй фактор отключён настройкой", request)
        return TokenPair(
            access_token=create_access_token(str(user.id), user.role.value),
            refresh_token=create_refresh_token(str(user.id)),
        )

    pre_auth_token = _create_pre_auth_token(user.id)

    if not user.totp_enabled:
        # Only generate a new secret if one doesn't already exist (prevents secret theft on repeated logins)
        if not user.totp_secret:
            user.totp_secret = totp_service.generate_totp_secret()
            db.commit()
        secret = user.totp_secret
        uri = totp_service.get_provisioning_uri(secret, user.username)
        qr = totp_service.generate_qr_code_base64(uri)
        return LoginTotpSetupRequired(pre_auth_token=pre_auth_token, provisioning_uri=uri, qr_code_base64=qr)

    return LoginTotpRequired(pre_auth_token=pre_auth_token)


def _ldap_login(db: Session, payload: LoginRequest, request: Request) -> User:
    """Доменная учётная запись: пароль проверяет AD, запись Fleet Manager создаётся при первом входе."""
    try:
        identity = ldap_auth.authenticate(payload.username, payload.password)
        user, created = ldap_users.sync_user(db, identity)
    except ldap_auth.LdapDenied as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    except ldap_auth.LdapUnavailable as exc:
        log.warning("LDAP login failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Домен недоступен, попробуйте позже")
    if created:
        record_audit(db, user.id, "user.ldap_create", f"Создан доменный пользователь {user.username} ({user.role.value})", request)
    return user


@router.get("/options")
def login_options():
    """Что показать на странице входа: включён ли вход доменной учётной записью."""
    config = ldap_config.current()
    return {"ldap_enabled": config.enabled, "ldap_domain": config.domain if config.enabled else None}


# SEC-02: Rate limiting — 5 TOTP attempts per pre_auth_token per 5 minutes.
@router.post("/totp/verify", response_model=TokenPair)
def verify_totp(payload: TotpVerifyRequest, request: Request, db: Session = Depends(get_db)):
    # Rate limit by token (first 32 chars as key) to prevent TOTP brute-force
    token_key = payload.pre_auth_token[:32] if len(payload.pre_auth_token) > 32 else payload.pre_auth_token
    if check_rate_limit(f"totp:{token_key}", limit=5, window_seconds=300):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Слишком много попыток. Повторите через 5 минут.")

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
    if user.auth_source == ldap_users.LDAP:
        _recheck_ldap(db, user)

    return TokenPair(
        access_token=create_access_token(str(user.id), user.role.value),
        refresh_token=create_refresh_token(str(user.id)),
    )


def _recheck_ldap(db: Session, user: User) -> None:
    """Отключённая в домене или исключённая из групп запись теряет доступ при обновлении токена."""
    if not ldap_auth.enabled():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Вход через домен выключен")
    if not ldap_auth.can_recheck() or not user.ldap_guid:
        return
    try:
        identity = ldap_auth.recheck(user.ldap_guid)
    except ldap_auth.LdapUnavailable as exc:
        # Сбой домена не выбрасывает из Fleet Manager тех, кто уже вошёл
        log.warning("LDAP recheck of %s skipped: %s", user.username, exc)
        return
    if identity is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Учётная запись отключена или исключена из групп доступа")
    renamed = identity.display_name != user.display_name
    user.display_name = identity.display_name
    if ldap_users.apply_role(user, identity.role) or renamed:
        db.commit()


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/change-password", status_code=status.HTTP_200_OK)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.auth_source == ldap_users.LDAP:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пароль доменной учётной записи меняется в домене")
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Текущий пароль неверный")
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Новый пароль должен отличаться от текущего",
        )

    user.password_hash = hash_password(payload.new_password)
    db.commit()
    record_audit(db, user.id, "user.change_password", "Пароль изменён", request)
    return {"detail": "Пароль изменён"}


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
