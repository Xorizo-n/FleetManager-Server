"""Локальные записи доменных пользователей: создаются при первом входе, роль и имя — из AD."""
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config import settings
from models.user import User
from services.ldap_auth import LdapDenied, LdapIdentity

LDAP = "ldap"
# Не bcrypt-хеш: локальная проверка пароля для доменной записи невозможна
NO_LOCAL_PASSWORD = "!ldap"


def find_local(db: Session, login: str) -> User | None:
    """Локальная учётная запись с таким именем — она важнее доменной (аварийный вход администратора)."""
    return db.execute(select(User).where(User.username == login.strip(), User.auth_source != LDAP)).scalar_one_or_none()


_EMAIL = TypeAdapter(EmailStr)


def _valid_email(value: str) -> bool:
    try:
        _EMAIL.validate_python(value)
        return True
    except ValidationError:
        return False


def _free_email(db: Session, user: User | None, candidates: list[str]) -> str:
    for email in filter(_valid_email, candidates):
        owner = db.execute(select(User).where(func.lower(User.email) == email.lower())).scalar_one_or_none()
        if owner is None or owner is user:
            return email
    raise LdapDenied("Email учётной записи уже занят другим пользователем Fleet Manager")


def sync_user(db: Session, identity: LdapIdentity) -> tuple[User, bool]:
    """Находит или создаёт пользователя по objectGUID и обновляет имя, email и роль. (user, created)."""
    user = db.execute(select(User).where(User.ldap_guid == identity.guid)).scalar_one_or_none()
    same_name = db.execute(select(User).where(func.lower(User.username) == identity.username.lower())).scalar_one_or_none()
    if same_name is not None and same_name is not user:
        if same_name.auth_source != LDAP:
            raise LdapDenied(f"Имя «{identity.username}» занято локальной учётной записью Fleet Manager")
        # Запись пересоздали в домене с тем же логином — продолжаем старую
        user = user or same_name

    fallback = f"{identity.username}@{settings.ldap_domain}".lower()
    email = _free_email(db, user, [e for e in (identity.email, fallback) if e])
    created = user is None
    if created:
        user = User(auth_source=LDAP, password_hash=NO_LOCAL_PASSWORD, username=identity.username, email=email, role=identity.role)
        db.add(user)
    user.ldap_guid = identity.guid
    user.username = identity.username
    user.email = email
    user.display_name = identity.display_name
    user.role = identity.role
    db.commit()
    db.refresh(user)
    return user, created
