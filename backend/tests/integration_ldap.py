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
from services import ldap_auth, ldap_config
from services.security import create_refresh_token, hash_password

settings.ldap_enabled = True
settings.totp_required = False
ldap_config.CACHE_SECONDS = 0
client = TestClient(app)
mock.patch("routers.auth.check_rate_limit", return_value=False).start()
db = SessionLocal()
db.query(User).filter(User.username.in_(["ivanov", "fm-local", "fm-helper"])).delete(synchronize_session=False)
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

# Роль, назначенная администратором, переживает вход; роль, равная групповой, снова отдаёт роль группам
from services import ldap_users  # noqa: E402

user = db.query(User).filter(User.ldap_guid == guid).one()
ldap_users.set_manual_role(user, UserRole.viewer)
db.commit()
assert user.role_override == UserRole.viewer
r, _ = login(result=ldap_auth.LdapIdentity(**{**identity.__dict__, "role": UserRole.admin}))
db.expire_all()
user = db.query(User).filter(User.ldap_guid == guid).one()
assert (user.role, user.ldap_role, user.role_override) == (UserRole.viewer, UserRole.admin, UserRole.viewer), (user.role, user.ldap_role)
ldap_users.set_manual_role(user, UserRole.admin)
db.commit()
assert user.role_override is None and user.role == UserRole.admin

# Ручное повышение через API администратора
r, _ = login(result=identity)  # группы: оператор
admin_token = r.json()["access_token"]
db.expire_all()
assert db.query(User).filter(User.ldap_guid == guid).one().role == UserRole.operator
helper = User(username="fm-helper", email="fm-helper@example.org", password_hash=hash_password("helper-pass-123"), role=UserRole.admin)
db.add(helper)
db.commit()
helper_token = client.post("/auth/login", json={"username": "fm-helper", "password": "helper-pass-123"}).json()["access_token"]
user = db.query(User).filter(User.ldap_guid == guid).one()
r = client.patch(f"/users/{user.id}/role", json={"role": "admin"}, headers={"Authorization": "Bearer " + helper_token})
assert r.status_code == 200 and r.json()["role"] == "admin" and r.json()["role_override"] == "admin" and r.json()["ldap_role"] == "operator", r.text
r, _ = login(result=identity)
db.expire_all()
assert db.query(User).filter(User.ldap_guid == guid).one().role == UserRole.admin
r = client.patch(f"/users/{user.id}/role", json={"role": "operator"}, headers={"Authorization": "Bearer " + helper_token})
assert r.status_code == 200 and r.json()["role_override"] is None, r.text
db.delete(db.get(User, helper.id))
db.commit()

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

# Настройки в интерфейсе: сохраняются в БД, пароль не возвращается, без групп не включить
from models.ldap_settings import LdapSettings  # noqa: E402

helper = User(username="fm-helper", email="fm-helper@example.org", password_hash=hash_password("helper-pass-123"), role=UserRole.admin)
db.add(helper)
db.commit()
auth_h = {"Authorization": "Bearer " + client.post("/auth/login", json={"username": "fm-helper", "password": "helper-pass-123"}).json()["access_token"]}
assert client.get("/settings/ldap", headers=auth_h).json()["source"] == "env"
body = {"enabled": True, "url": "ldaps://at.urfu.ru", "domain": "at.urfu.ru", "base_dn": "DC=at,DC=urfu,DC=ru",
        "bind_dn": "svc@at.urfu.ru", "bind_password": "svc-secret", "operator_groups": ["CN=Staff,DC=at,DC=urfu,DC=ru"]}
assert client.put("/settings/ldap", json={**body, "operator_groups": []}, headers=auth_h).status_code == 400
r = client.put("/settings/ldap", json=body, headers=auth_h)
assert r.status_code == 200, r.text
out = client.get("/settings/ldap", headers=auth_h).json()
assert out["source"] == "db" and out["has_bind_password"] and "bind_password" not in out and "svc-secret" not in r.text, out
row = db.get(LdapSettings, 1)
assert row.bind_password_encrypted and "svc-secret" not in row.bind_password_encrypted
assert ldap_config.current().bind_password == "svc-secret" and ldap_config.current().operator_groups == ["CN=Staff,DC=at,DC=urfu,DC=ru"]
# Пароль не введён заново — остаётся; пустая строка — удаляется
client.put("/settings/ldap", json={**body, "bind_password": None, "viewer_groups": ["CN=V,DC=at,DC=urfu,DC=ru"]}, headers=auth_h)
assert ldap_config.current().bind_password == "svc-secret"
client.put("/settings/ldap", json={**body, "bind_password": ""}, headers=auth_h)
assert ldap_config.current().bind_password == "" and not client.get("/settings/ldap", headers=auth_h).json()["has_bind_password"]
# Проверка черновика без служебной записи — понятная ошибка, а не 500
r = client.post("/settings/ldap/check", json={**body, "bind_password": ""}, headers=auth_h)
assert r.status_code == 200 and r.json()["ok"] is False and "служебная" in r.json()["error"].lower(), r.text
# Не администратор настройки не видит
assert client.get("/settings/ldap").status_code == 401
db.delete(db.get(LdapSettings, 1))
db.commit()

db.query(User).filter(User.username.in_(["ivanov", "fm-local", "fm-helper"])).delete(synchronize_session=False)
db.commit()
print("integration_ldap: ok")
