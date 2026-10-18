"""Настройки входа через домен в интерфейсе: служебная запись и группы ролей. Только администратор."""
from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_roles
from models.ldap_settings import LdapSettings
from models.user import User, UserRole
from services import ldap_auth, ldap_config
from services.audit import record_audit
from services.crypto import encrypt_secret

router = APIRouter(prefix="/settings/ldap", tags=["settings"])
admin_only = require_roles(UserRole.admin)

ROLE_FIELDS = ("admin_groups", "operator_groups", "viewer_groups")


class LdapSettingsIn(BaseModel):
    enabled: bool
    url: str = Field(min_length=1, max_length=512)
    domain: str = Field(min_length=1, max_length=255)
    base_dn: str = Field(min_length=1, max_length=512)
    bind_dn: str = Field(default="", max_length=512)
    # None — оставить сохранённый пароль, "" — удалить
    bind_password: str | None = Field(default=None, max_length=256)
    admin_groups: list[str] = Field(default_factory=list, max_length=50)
    operator_groups: list[str] = Field(default_factory=list, max_length=50)
    viewer_groups: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("url")
    @classmethod
    def _urls(cls, value: str) -> str:
        urls = [u.strip() for u in value.split(",") if u.strip()]
        if not urls or any(not u.lower().startswith(("ldaps://", "ldap://")) for u in urls):
            raise ValueError("Адрес — ldaps://сервер (или ldap:// со StartTLS), несколько через запятую")
        return ", ".join(urls)

    @field_validator("domain", "base_dn", "bind_dn")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator(*ROLE_FIELDS)
    @classmethod
    def _groups(cls, value: list[str]) -> list[str]:
        groups = []
        for dn in (g.strip() for g in value):
            if not dn:
                continue
            if "=" not in dn or len(dn) > 512:
                raise ValueError(f"Не похоже на DN группы: {dn[:80]}")
            if dn.lower() not in (g.lower() for g in groups):
                groups.append(dn)
        return groups


class LdapCheckIn(LdapSettingsIn):
    username: str | None = Field(default=None, max_length=128)


class GroupSearchIn(LdapSettingsIn):
    query: str = Field(min_length=2, max_length=64)


def _out(config: ldap_config.LdapConfig, row: LdapSettings | None) -> dict:
    return {
        "enabled": config.enabled,
        "url": config.url,
        "domain": config.domain,
        "base_dn": config.base_dn,
        "bind_dn": config.bind_dn,
        "has_bind_password": bool(config.bind_password),
        "admin_groups": config.admin_groups,
        "operator_groups": config.operator_groups,
        "viewer_groups": config.viewer_groups,
        "source": config.source,
        "updated_at": row.updated_at if row else None,
    }


def _draft(db: Session, payload: LdapSettingsIn) -> ldap_config.LdapConfig:
    """Настройки из формы поверх сохранённых; пароль, не введённый заново, — сохранённый."""
    saved = ldap_config.load(db)
    return replace(
        saved,
        enabled=payload.enabled,
        url=payload.url,
        domain=payload.domain,
        base_dn=payload.base_dn,
        bind_dn=payload.bind_dn,
        bind_password=saved.bind_password if payload.bind_password is None else payload.bind_password,
        admin_groups=payload.admin_groups,
        operator_groups=payload.operator_groups,
        viewer_groups=payload.viewer_groups,
    )


@router.get("")
def get_settings(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    return _out(ldap_config.load(db), db.get(LdapSettings, 1))


@router.put("")
def save_settings(payload: LdapSettingsIn, request: Request, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    if payload.enabled and not any(getattr(payload, f) for f in ROLE_FIELDS):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Укажите хотя бы одну группу доступа: без групп через домен не войдёт никто")
    before = ldap_config.load(db)
    row = db.get(LdapSettings, 1)
    if row is None:
        # Первое сохранение: пароль из .env переезжает в БД, если его не ввели заново
        row = LdapSettings(id=1, bind_password_encrypted=encrypt_secret(before.bind_password) if before.bind_password else None)
        db.add(row)
    row.enabled = payload.enabled
    row.url = payload.url
    row.domain = payload.domain
    row.base_dn = payload.base_dn
    row.bind_dn = payload.bind_dn
    if payload.bind_password is not None:
        row.bind_password_encrypted = encrypt_secret(payload.bind_password) if payload.bind_password else None
    for f in ROLE_FIELDS:
        setattr(row, f, getattr(payload, f))
    row.updated_by = admin.id
    db.commit()
    db.refresh(row)
    ldap_config.invalidate()

    after = ldap_config.from_row(row)
    changes = [f"{name}: {getattr(before, name)!r} -> {getattr(after, name)!r}"
               for name in ("enabled", "url", "domain", "base_dn", "bind_dn", *ROLE_FIELDS)
               if getattr(before, name) != getattr(after, name)]
    if payload.bind_password is not None:
        changes.append("пароль служебной записи " + ("изменён" if payload.bind_password else "удалён"))
    record_audit(db, admin.id, "settings.ldap", "; ".join(changes) or "без изменений", request)
    return _out(after, row)


@router.post("/check")
def check_settings(payload: LdapCheckIn, db: Session = Depends(get_db), _: User = Depends(admin_only)):
    """Проверяет настройки из формы до сохранения: служебную запись, группы, роль пользователя."""
    with ldap_config.use(_draft(db, payload)):
        try:
            return {"ok": True, **ldap_auth.diagnose(payload.username or None)}
        except ldap_auth.LdapUnavailable as exc:
            return {"ok": False, "error": str(exc)}


@router.post("/groups")
def search_groups(payload: GroupSearchIn, db: Session = Depends(get_db), _: User = Depends(admin_only)):
    with ldap_config.use(_draft(db, payload)):
        try:
            return ldap_auth.search_groups(payload.query)
        except ldap_auth.LdapUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
