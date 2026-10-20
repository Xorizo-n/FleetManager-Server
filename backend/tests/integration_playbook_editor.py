"""Редактор плейбуков через API на настоящей БД: создание, правка, переименование с расписанием, удаление.

Запуск на копии схемы: DATABASE_URL=.../fm_migtest LOCAL_PLAYBOOKS_DIR=/tmp/lp-test python tests/integration_playbook_editor.py
"""
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from config import settings
from database import SessionLocal
from main import app
from models.playbook import PlaybookRepo, PlaybookSchedule
from models.user import User, UserRole
from services.security import hash_password

settings.totp_required = False
mock.patch("routers.auth.check_rate_limit", return_value=False).start()
client = TestClient(app)
db = SessionLocal()
for name in ("fm-editor", "fm-viewer"):
    db.query(User).filter(User.username == name).delete()
db.add_all([
    User(username="fm-editor", email="fm-editor@example.org", password_hash=hash_password("editor-pass-123"), role=UserRole.operator),
    User(username="fm-viewer", email="fm-viewer@example.org", password_hash=hash_password("viewer-pass-123"), role=UserRole.viewer),
])
db.commit()


def auth(name, password):
    token = client.post("/auth/login", json={"username": name, "password": password}).json()["access_token"]
    return {"Authorization": "Bearer " + token}


op, viewer = auth("fm-editor", "editor-pass-123"), auth("fm-viewer", "viewer-pass-123")
GOOD = "- name: Ping\n  hosts: Win_Hosts\n  gather_facts: false\n  tasks:\n    - ansible.windows.win_ping:\n"

# Источник «Fleet Manager» появляется сам; наблюдатель редактор не видит
repos = client.get("/playbooks/repos", headers=op).json()
local = next(r for r in repos if r["kind"] == "local")
assert local["name"] == "Fleet Manager", repos
assert client.get("/playbooks/repos", headers=viewer).status_code == 403
assert client.put("/playbooks/local/file", json={"path": "x.yml", "content": GOOD}, headers=viewer).status_code == 403
assert client.post(f"/playbooks/repos/{local['id']}/sync", headers=op).status_code == 400

# Создание: ошибка не сохраняется, верный плейбук сохраняется и виден в каталоге
r = client.put("/playbooks/local/file", json={"path": "check/ping.yml", "content": "- name: x\n  tasks: []\n"}, headers=op)
assert r.status_code == 422 and "hosts" in r.json()["detail"], r.text
r = client.put("/playbooks/local/file", json={"path": "check/ping.yml", "content": GOOD}, headers=op)
assert r.status_code == 200 and r.json()["editable"], r.text
files = client.get(f"/playbooks/repos/{local['id']}/files", headers=op).json()
assert [f["path"] for f in files] == ["check/ping.yml"] and files[0]["display_name"] == "Ping", files
assert client.put("/playbooks/local/file", json={"path": "check/ping.yml", "content": GOOD}, headers=op).status_code == 409
assert client.put("/playbooks/local/file", json={"path": "../evil.yml", "content": GOOD}, headers=op).status_code == 400
content = client.get(f"/playbooks/repos/{local['id']}/content", params={"path": "check/ping.yml"}, headers=op).json()
assert content["content"] == GOOD and content["editable"]
assert client.get(f"/playbooks/repos/{local['id']}/content", params={"path": "../../etc/passwd"}, headers=op).status_code == 400
# Модуля нет — syntax-check не пускает
r = client.put("/playbooks/local/file", json={"path": "check/ping.yml", "content": GOOD.replace("win_ping", "win_pingg"), "original_path": "check/ping.yml"}, headers=op)
assert r.status_code == 422 and "win_pingg" in r.json()["detail"], r.text

# Переименование переносит расписание; удалить плейбук с расписанием нельзя
schedule = PlaybookSchedule(repo_id=local["id"], playbook_name="check/ping.yml", host_ids=[], host_group_ids=[], cron_expression="0 3 * * *")
db.add(schedule)
db.commit()
r = client.put("/playbooks/local/file", json={"path": "check/ping2.yml", "content": GOOD.replace("Ping", "Ping 2"), "original_path": "check/ping.yml"}, headers=op)
assert r.status_code == 200, r.text
db.refresh(schedule)
assert schedule.playbook_name == "check/ping2.yml"
assert not (Path(settings.local_playbooks_dir) / "check/ping.yml").exists()
r = client.delete("/playbooks/local/file", params={"path": "check/ping2.yml"}, headers=op)
assert r.status_code == 409 and "расписани" in r.json()["detail"], r.text
db.delete(schedule)
db.commit()
assert client.delete("/playbooks/local/file", params={"path": "check/ping2.yml"}, headers=op).status_code == 204
assert not (Path(settings.local_playbooks_dir) / "check").exists()

# Плейбук из git — только просмотр
git_repo = db.query(PlaybookRepo).filter(PlaybookRepo.kind == "git").first()
if git_repo is not None:
    some = client.get(f"/playbooks/repos/{git_repo.id}/files", headers=op).json()
    if some:
        assert client.get(f"/playbooks/repos/{git_repo.id}/content", params={"path": some[0]["path"]}, headers=op).json()["editable"] is False

for name in ("fm-editor", "fm-viewer"):
    db.query(User).filter(User.username == name).delete()
db.query(PlaybookRepo).filter(PlaybookRepo.kind == "local").delete()
db.commit()
print("integration_playbook_editor: ok")
