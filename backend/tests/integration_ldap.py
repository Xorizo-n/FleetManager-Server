"""Вход доменной учётной записью на настоящей БД (домен подменён): создание, обновление, отказы.

Запуск на копии схемы: DATABASE_URL=.../fm_migtest python tests/integration_ldap.py
"""
import uuid
from unittest import mock

from fastapi.testclient import TestClient

from config import settings
from database import SessionLocal
from main import app
from models.user import User, UserRole
from services import ldap_auth
from services.security import create_refresh_token, hash_password

settings.ldap_enabled = True
settings.totp_required = False
client = TestClient(app)
db = SessionLocal()
db.query(User).filter(User.username.in_(["ivanov", "fm-local"])).delete(synchronize_session=False)
db.commit()

guid = str(uuid.uuid4())
identity = ldap_auth.LdapIdentity(username="ivanov", guid=guid, email="I.I.Ivanov@urfu.ru", display_name="Иванов Иван", role=UserRole.operator)


def login(username="AT\\ivanov", password="secret", result=identity):
    effect = result if isinstance(result, Exception) else None
    with mock.patch.object(ldap_auth, "authenticate", return_value=result, side_effect=effect) as auth:
        response = client.post("/auth/login", json={"username": username, "password": password})
    return response, auth


# Первый вход создаёт доменного пользователя
r, auth = login()
assert r.status_code == 200 and r.json()["status"] == "ok", r.text
auth.assert_called_once_with("AT\\ivanov", "secret")
user = db.query(User).filter(User.ldap_guid == guid).one()
assert (user.username, user.auth_source, user.role, user.email, user.display_name) == ("ivanov", "ldap", UserRole.operator, "I.I.Ivanov@urfu.ru", "Иванов Иван")
me = client.get("/auth/me", headers={"Authorization": "Bearer " + r.json()["access_token"]}).json()
assert me["auth_source"] == "ldap" and me["display_name"] == "Иванов Иван", me

# Повторный вход обновляет роль, а не создаёт второго
r, _ = login(result=ldap_auth.LdapIdentity(**{**identity.__dict__, "role": UserRole.admin}))
assert r.status_code == 200
db.expire_all()
assert db.query(User).filter(User.ldap_guid == guid).one().role == UserRole.admin
assert db.query(User).filter(User.username == "ivanov").count() == 1

# Отказ домена и недоступность домена
r, _ = login(result=ldap_auth.LdapDenied("Неверный логин или пароль"))
assert r.status_code == 401 and r.json()["detail"] == "Неверный логин или пароль"
r, _ = login(result=ldap_auth.LdapUnavailable("timeout"))
assert r.status_code == 503

# Пароль доменной записи в Fleet Manager не меняется, роль вручную — тоже
token = login()[0].json()["access_token"]
r = client.post("/auth/change-password", json={"current_password": "secret", "new_password": "something-new"}, headers={"Authorization": "Bearer " + token})
assert r.status_code == 400, r.text

# Заблокированный в Fleet Manager доменный пользователь не входит
user = db.query(User).filter(User.ldap_guid == guid).one()
user.is_active = False
db.commit()
assert login()[0].status_code == 401
user.is_active = True
db.commit()

# Обновление токена: с служебной записью — перепроверка в домене
refresh = create_refresh_token(str(user.id))
with mock.patch.object(settings, "ldap_bind_dn", "CN=svc"), mock.patch.object(ldap_auth, "recheck", return_value=None):
    assert client.post("/auth/refresh", json={"refresh_token": refresh}).status_code == 401
with mock.patch.object(settings, "ldap_bind_dn", "CN=svc"), mock.patch.object(ldap_auth, "recheck", return_value=ldap_auth.LdapIdentity(**{**identity.__dict__, "role": UserRole.viewer})):
    assert client.post("/auth/refresh", json={"refresh_token": refresh}).status_code == 200
db.expire_all()
assert db.get(User, user.id).role == UserRole.viewer
with mock.patch.object(settings, "ldap_bind_dn", "CN=svc"), mock.patch.object(ldap_auth, "recheck", side_effect=ldap_auth.LdapUnavailable("down")):
    assert client.post("/auth/refresh", json={"refresh_token": refresh}).status_code == 200
settings.ldap_enabled = False
assert client.post("/auth/refresh", json={"refresh_token": refresh}).status_code == 401
settings.ldap_enabled = True

# Локальная запись с тем же именем важнее домена и домен не вызывается
local = User(username="fm-local", email="fm-local@example.org", password_hash=hash_password("local-pass-123"), role=UserRole.viewer)
db.add(local)
db.commit()
r, auth = login(username="fm-local", password="local-pass-123")
assert r.status_code == 200 and not auth.called
r, auth = login(username="fm-local", password="wrong")
assert r.status_code == 401 and not auth.called
# Доменная запись с именем локальной не создаётся
r, _ = login(username="AT\\fm-local", result=ldap_auth.LdapIdentity(username="fm-local", guid=str(uuid.uuid4()), email=None, display_name=None, role=UserRole.viewer))
assert r.status_code == 401 and "локальной" in r.json()["detail"], r.text

db.query(User).filter(User.username.in_(["ivanov", "fm-local"])).delete(synchronize_session=False)
db.commit()
print("integration_ldap: ok")
