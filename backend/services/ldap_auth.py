"""Вход доменной учётной записью Active Directory (at.urfu.ru) по LDAPS.

Пароль проверяется простым bind'ом от имени пользователя, роль Fleet Manager — по членству
в группах AD (вложенные группы учитываются, правило LDAP_MATCHING_RULE_IN_CHAIN). Доступ
получают только участники групп ролей (Администрирование → «Вход через домен», иначе LDAP_*_GROUPS
из .env — services/ldap_config.py): без групп в домен входят и студенты, поэтому «любой
пользователь домена» не пускается никогда.

Служебная учётная запись необязательна: без неё пользователь ищет сам себя
после своего bind'а. С ней сервер при каждом обновлении токена перепроверяет, что запись не
отключена и всё ещё состоит в группах, — иначе доступ живёт до истечения refresh-токена.
"""
from __future__ import annotations

import logging
import ssl
import uuid
from dataclasses import dataclass

from models.user import UserRole
from services import ldap_config

log = logging.getLogger(__name__)

IN_CHAIN = "1.2.840.113556.1.4.1941"
ACCOUNT_DISABLED = 0x2
INVALID_CREDENTIALS = 49
NO_SUCH_OBJECT = 32
ATTRIBUTES = ["sAMAccountName", "mail", "userPrincipalName", "displayName", "userAccountControl", "objectGUID"]
ROLE_ORDER = (UserRole.admin, UserRole.operator, UserRole.viewer)


class LdapUnavailable(Exception):
    """Контроллеры домена недоступны или служебная учётная запись не подошла."""


class LdapDenied(Exception):
    """Вход отклонён; текст исключения показывается пользователю."""


@dataclass(frozen=True)
class LdapIdentity:
    username: str
    guid: str
    email: str | None
    display_name: str | None
    role: UserRole


def _c() -> ldap_config.LdapConfig:
    return ldap_config.current()


def enabled() -> bool:
    return _c().enabled


def split_login(login: str) -> str | None:
    """sAMAccountName из «ivanov», «AT\\ivanov» или «ivanov@at.urfu.ru»; None — чужой домен."""
    login = login.strip()
    if "\\" in login:
        login = login.rsplit("\\", 1)[1]
    elif "@" in login:
        login, _, suffix = login.rpartition("@")
        if suffix.lower() != _c().domain.lower():
            return None
    if not login or len(login) > 64 or any(c in login for c in '"/\\[]:;|=,+*?<>@'):
        return None
    return login


def role_groups() -> list[tuple[UserRole, list[str]]]:
    """Группы ролей из настроек, от старшей роли к младшей."""
    c = _c()
    raw = {UserRole.admin: c.admin_groups, UserRole.operator: c.operator_groups, UserRole.viewer: c.viewer_groups}
    return [(role, [g.strip() for g in raw[role] if g.strip()]) for role in ROLE_ORDER]


def _escape(value: str) -> str:
    from ldap3.utils.conv import escape_filter_chars

    return escape_filter_chars(value)


def _servers():
    from ldap3 import FIRST, NONE, Server, ServerPool, Tls

    c = _c()
    tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=c.ca_cert or None)
    servers = [
        Server(url.strip(), use_ssl=url.strip().lower().startswith("ldaps://"), tls=tls,
               connect_timeout=c.timeout_seconds, get_info=NONE)
        for url in c.url.split(",") if url.strip()
    ]
    if not servers:
        raise LdapUnavailable("Не задан адрес контроллера домена")
    return ServerPool(servers, FIRST, active=1, exhaust=60)


def _bind(user: str, password: str):
    """Открытое соединение после успешного bind'а; None — неверный логин или пароль."""
    from ldap3 import SIMPLE, Connection
    from ldap3.core.exceptions import LDAPException

    try:
        conn = Connection(_servers(), user=user, password=password, authentication=SIMPLE, read_only=True,
                          receive_timeout=_c().timeout_seconds, raise_exceptions=False)
        conn.open()
        if not conn.server.ssl:
            conn.start_tls()
        if conn.bind():
            return conn
        result = conn.result.get("result")
        conn.unbind()
    except LDAPException as exc:
        raise LdapUnavailable(f"Контроллер домена недоступен: {exc}") from exc
    if result == INVALID_CREDENTIALS:
        return None
    raise LdapUnavailable(f"Контроллер домена отклонил bind: {result}")


def _service_bind():
    c = _c()
    if not c.bind_dn or not c.bind_password:
        raise LdapUnavailable("Не задана служебная учётная запись")
    conn = _bind(c.bind_dn, c.bind_password)
    if conn is None:
        raise LdapUnavailable("Служебная учётная запись не подошла: неверный логин или пароль")
    return conn


def _first(attrs: dict, name: str):
    value = attrs.get(name)
    if isinstance(value, list):
        value = value[0] if value else None
    return value if value not in ("", None) else None


def _find(conn, search_filter: str, base: str | None = None):
    from ldap3 import BASE, SUBTREE

    ok = conn.search(base or _c().base_dn, search_filter, BASE if base else SUBTREE,
                     attributes=ATTRIBUTES, size_limit=2)
    if not ok or len(conn.entries) != 1:
        return None
    return conn.entries[0]


def _find_user(conn, username: str):
    return _find(conn, _c().user_filter.format(username=_escape(username)))


def _role(conn, user_dn: str) -> UserRole | None:
    from ldap3 import BASE

    for role, groups in role_groups():
        for group in groups:
            if conn.search(user_dn, f"(memberOf:{IN_CHAIN}:={_escape(group)})", BASE, attributes=[]) and conn.entries:
                return role
    return None


def _guid(value) -> str:
    """objectGUID: без схемы (get_info=NONE) ldap3 отдаёт сырые 16 байт, со схемой — строку «{…}»."""
    if isinstance(value, (bytes, bytearray)):
        return str(uuid.UUID(bytes_le=bytes(value)))
    return str(uuid.UUID(str(value).strip("{}")))


def _identity(conn, entry) -> LdapIdentity | None:
    attrs = entry.entry_attributes_as_dict
    control = _first(attrs, "userAccountControl")
    if control is not None and int(control) & ACCOUNT_DISABLED:
        return None
    role = _role(conn, entry.entry_dn)
    if role is None:
        return None
    return LdapIdentity(
        username=str(_first(attrs, "sAMAccountName")),
        guid=_guid(_first(attrs, "objectGUID")),
        email=_first(attrs, "mail") or _first(attrs, "userPrincipalName"),
        display_name=_first(attrs, "displayName"),
        role=role,
    )


def authenticate(login: str, password: str) -> LdapIdentity:
    """Проверяет пароль в домене и определяет роль. LdapDenied — отказ, LdapUnavailable — домен недоступен."""
    username = split_login(login)
    # Пустой пароль AD принимает как анонимный bind — без этой проверки вошёл бы кто угодно
    if username is None or not password:
        raise LdapDenied("Неверный логин или пароль")
    if not any(groups for _, groups in role_groups()):
        log.warning("LDAP включён, но группы ролей (LDAP_*_GROUPS) не заданы — вход через домен закрыт")
        raise LdapDenied("Вход через домен не настроен: не заданы группы доступа")

    if _c().bind_dn:
        conn = _service_bind()
        try:
            entry = _find_user(conn, username)
            if entry is None:
                raise LdapDenied("Неверный логин или пароль")
            user_conn = _bind(entry.entry_dn, password)
            if user_conn is None:
                raise LdapDenied("Неверный логин или пароль")
            user_conn.unbind()
            identity = _identity(conn, entry)
        finally:
            conn.unbind()
    else:
        # sAMAccountName@домен — неявный UPN, AD принимает его, даже если UPN записи другой
        conn = _bind(f"{username}@{_c().domain}", password)
        if conn is None:
            raise LdapDenied("Неверный логин или пароль")
        try:
            entry = _find_user(conn, username)
            identity = _identity(conn, entry) if entry is not None else None
        finally:
            conn.unbind()

    if identity is None:
        raise LdapDenied("Учётная запись отключена или не входит в группы доступа Fleet Manager")
    return identity


def can_recheck() -> bool:
    return enabled() and bool(_c().bind_dn)


def recheck(guid: str) -> LdapIdentity | None:
    """Текущее состояние записи по objectGUID: None — удалена, отключена или вне групп доступа."""
    raw = uuid.UUID(guid).bytes_le
    conn = _service_bind()
    try:
        entry = _find(conn, "(objectGUID=" + "".join(f"\\{b:02x}" for b in raw) + ")")
        return _identity(conn, entry) if entry is not None else None
    finally:
        conn.unbind()


def _text(value) -> str | None:
    value = _first({"v": value}, "v")
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8", "replace")
    return value


def search_groups(query: str, limit: int = 30) -> list[dict]:
    """Группы домена по части имени или описания — для выбора в настройках. Нужна служебная запись."""
    from ldap3 import SUBTREE

    query = query.strip()
    if len(query) < 2:
        return []
    q = _escape(query)
    conn = _service_bind()
    try:
        conn.search(_c().base_dn, f"(&(objectClass=group)(|(cn=*{q}*)(description=*{q}*)))", SUBTREE,
                    attributes=["cn", "description"], size_limit=limit)
        groups = [{"dn": e.entry_dn, "name": _text(e.entry_attributes_as_dict.get("cn")) or e.entry_dn,
                   "description": _text(e.entry_attributes_as_dict.get("description"))} for e in conn.entries]
    finally:
        conn.unbind()
    return sorted(groups, key=lambda g: g["name"].lower())


MEMBER_LIMIT = 1000


def diagnose(username: str | None = None) -> dict:
    """Проверка настроек для формы: служебная запись, группы (есть ли, сколько участников), роль пользователя."""
    from ldap3 import BASE, SUBTREE

    c = _c()
    report: dict = {"bind": None, "groups": [], "user": None}
    conn = _service_bind()
    try:
        report["bind"] = "ok"
        for role, groups in role_groups():
            for group in groups:
                item = {"dn": group, "role": role.value, "found": False, "members": None}
                if conn.search(group, "(objectClass=group)", BASE, attributes=["cn"]) and conn.entries:
                    item["found"] = True
                    conn.search(c.base_dn, f"(&(objectCategory=person)(objectClass=user)(memberOf:{IN_CHAIN}:={_escape(group)}))",
                                SUBTREE, attributes=[], size_limit=MEMBER_LIMIT)
                    item["members"] = len(conn.entries)
                report["groups"].append(item)
        if username:
            name = split_login(username)
            entry = _find_user(conn, name) if name else None
            if entry is None:
                report["user"] = {"username": username, "found": False}
            else:
                identity = _identity(conn, entry)
                attrs = entry.entry_attributes_as_dict
                report["user"] = {
                    "username": _text(attrs.get("sAMAccountName")),
                    "found": True,
                    "display_name": _text(attrs.get("displayName")),
                    "role": identity.role.value if identity else None,
                }
    finally:
        conn.unbind()
    return report
