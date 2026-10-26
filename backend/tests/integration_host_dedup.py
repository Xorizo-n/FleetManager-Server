"""Слияние дублей хоста на настоящей БД: перенос истории, ПО, обоев, ссылок из задач, удаление учётки.

Запуск на копии схемы: DATABASE_URL=.../fm_migtest python tests/integration_host_dedup.py
"""
import uuid
from datetime import datetime, timedelta, timezone

from database import SessionLocal
from models.agent import AgentAlert
from models.credential import Credential, CredentialType
from models.host import Host, HostOS, HostStatus, HostStatusHistory
from models.software import InstallMethod, SoftwareItem
from models.task import TaskRun, TaskStatus, TaskType
from services.host_dedup import absorb_stale_twins, adoptable_host

db = SessionLocal()
now = datetime.now(timezone.utc)


def cleanup():
    db.query(TaskRun).filter(TaskRun.playbook_name == "it-dedup").delete(synchronize_session=False)
    db.query(Host).filter(Host.hostname.like("IT-DEDUP-%")).delete(synchronize_session=False)
    db.query(Credential).filter(Credential.name.like("it-dedup-%")).delete(synchronize_session=False)
    db.commit()


def credential(name):
    c = Credential(name=f"it-dedup-{name}", type=CredentialType.ssh_key, login="admin", secret_encrypted="x", is_agent_managed=True)
    db.add(c)
    db.flush()
    return c


cleanup()
old_cred, new_cred = credential("old"), credential("new")
old = Host(hostname="IT-DEDUP-1", os=HostOS.windows_11, status=HostStatus.offline, is_agent_managed=True, agent_id=uuid.uuid4(),
           ip_address="10.99.0.5", hw_serial_number="AirDisk 512GB SSD (477 GB)", comment="Это E201 PC1",
           credential_id=old_cred.id, last_seen_at=now - timedelta(days=1))
new = Host(hostname="IT-DEDUP-1", os=HostOS.windows_11, status=HostStatus.online, is_agent_managed=True, agent_id=uuid.uuid4(),
           agent_token_hash="newtoken", ip_address="10.99.0.5", hw_serial_number="S07TEST", hw_mac_address="00-11-22-33-44-55",
           agent_version="2026.10.25.25", credential_id=new_cred.id, last_seen_at=now)
other = Host(hostname="IT-DEDUP-2", os=HostOS.windows_11, status=HostStatus.online)
db.add_all([old, new, other])
db.flush()
db.add_all([
    HostStatusHistory(host_id=old.id, status=HostStatus.online),
    HostStatusHistory(host_id=new.id, status=HostStatus.online),
    AgentAlert(host_id=old.id, alert_type="hardware_changed", message="old"),
    SoftwareItem(host_id=old.id, name="Old app", install_method=InstallMethod.other),
    SoftwareItem(host_id=new.id, name="New app", install_method=InstallMethod.other),
    TaskRun(task_type=TaskType.playbook, playbook_name="it-dedup", status=TaskStatus.waiting,
            host_ids=[str(new.id), str(other.id)], host_states={str(new.id): "waiting", str(other.id): "success"}),
])
db.commit()
old_id, new_id, new_agent = old.id, new.id, new.agent_id

# Повторная регистрация: имя занято живой записью — не отдаём
assert adoptable_host(db, "IT-DEDUP-1", now) is None, "a reporting namesake must block adoption"

kept = absorb_stale_twins(db, new, now)
db.expire_all()
assert kept.id == old_id, "the old record must survive"
kept = db.get(Host, old_id)
assert db.get(Host, new_id) is None, "the new record must be gone"
assert kept.agent_id == new_agent and kept.agent_token_hash == "newtoken", "the agent identity must move"
assert kept.hw_serial_number == "S07TEST" and kept.agent_version == "2026.10.25.25" and kept.status == HostStatus.online
assert kept.comment == "Это E201 PC1", "the comment of the old record stays"
assert kept.credential_id == new_cred.id, "the key the agent installed is the new one"
assert db.get(Credential, old_cred.id) is None, "the unused agent credential of the old install is removed"
assert db.query(HostStatusHistory).filter_by(host_id=old_id).count() == 2
assert db.query(AgentAlert).filter_by(host_id=old_id).count() == 1
assert [s.name for s in db.query(SoftwareItem).filter_by(host_id=old_id)] == ["New app"], "software is the new inventory"
task = db.query(TaskRun).filter_by(playbook_name="it-dedup").one()
assert task.host_ids == [str(old_id), str(other.id)], task.host_ids
assert task.host_states == {str(old_id): "waiting", str(other.id): "success"}, task.host_states

# Запись снова уходит в офлайн — теперь её может занять повторная регистрация этого же имени
kept.last_seen_at = now - timedelta(hours=2)
db.commit()
assert adoptable_host(db, "IT-DEDUP-1", now).id == old_id

cleanup()
print("INTEGRATION_HOST_DEDUP_OK")
