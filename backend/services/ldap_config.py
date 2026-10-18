"""Действующие настройки входа через домен: из интерфейса (таблица ldap_settings), иначе LDAP_* из .env.

Сертификат CA, фильтр записей пользователей и таймаут задаются только в .env.
"""
from __future__ import annotations

import contextlib
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass, field, replace

from config import settings

log = logging.getLogger(__name__)

CACHE_SECONDS = 15
_cache: tuple[float, "LdapConfig"] | None = None
# Черновик из формы «Проверить»: действует только внутри запроса (contextvars не делятся между потоками)
_draft: ContextVar["LdapConfig | None"] = ContextVar("ldap_draft", default=None)


def split_groups(raw: str) -> list[str]:
    """DN групп из .env разделяются «;»: в самих DN есть запятые."""
    return [g.strip() for g in raw.split(";") if g.strip()]


@dataclass(frozen=True)
class LdapConfig:
    enabled: bool
    url: str
    domain: str
    base_dn: str
    bind_dn: str = ""
    bind_password: str = field(default="", repr=False)
    admin_groups: list[str] = field(default_factory=list)
    operator_groups: list[str] = field(default_factory=list)
    viewer_groups: list[str] = field(default_factory=list)
    source: str = "env"
    ca_cert: str = ""
    person_filter: str = "(&(objectCategory=person)(objectClass=user))"
    timeout_seconds: int = 5


def from_settings() -> LdapConfig:
    return LdapConfig(
        enabled=settings.ldap_enabled,
        url=settings.ldap_url,
        domain=settings.ldap_domain,
        base_dn=settings.ldap_base_dn,
        bind_dn=settings.ldap_bind_dn,
        bind_password=settings.ldap_bind_password,
        admin_groups=split_groups(settings.ldap_admin_groups),
        operator_groups=split_groups(settings.ldap_operator_groups),
        viewer_groups=split_groups(settings.ldap_viewer_groups),
        ca_cert=settings.ldap_ca_cert,
        person_filter=settings.ldap_person_filter,
        timeout_seconds=settings.ldap_timeout_seconds,
    )


def from_row(row) -> LdapConfig:
    from services.crypto import decrypt_secret

    password = ""
    if row.bind_password_encrypted:
        try:
            password = decrypt_secret(row.bind_password_encrypted)
        except Exception:  # noqa: BLE001 — сменили CREDENTIAL_ENCRYPTION_KEY
            log.warning("LDAP bind password cannot be decrypted; set it again in the UI")
    return replace(
        from_settings(),
        enabled=row.enabled,
        url=row.url,
        domain=row.domain,
        base_dn=row.base_dn,
        bind_dn=row.bind_dn,
        bind_password=password,
        admin_groups=list(row.admin_groups or []),
        operator_groups=list(row.operator_groups or []),
        viewer_groups=list(row.viewer_groups or []),
        source="db",
    )


def load(db) -> LdapConfig:
    from models.ldap_settings import LdapSettings

    row = db.get(LdapSettings, 1)
    return from_row(row) if row is not None else from_settings()


def current() -> LdapConfig:
    """Настройки для входа: черновик проверки, иначе сохранённые (кэш на CACHE_SECONDS)."""
    global _cache
    draft = _draft.get()
    if draft is not None:
        return draft
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    from database import SessionLocal

    db = SessionLocal()
    try:
        config = load(db)
    finally:
        db.close()
    _cache = (now, config)
    return config


def invalidate() -> None:
    global _cache
    _cache = None


@contextlib.contextmanager
def use(config: LdapConfig):
    """Временно действуют эти настройки (проверка формы до сохранения)."""
    token = _draft.set(config)
    try:
        yield
    finally:
        _draft.reset(token)
