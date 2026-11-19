"""Online status is evaluated at each scheduled dispatch, not at creation."""
import unittest
import uuid
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.host import Host, HostGroup, HostOS, HostStatus, HostTag
from models.playbook import PlaybookRepo, PlaybookSchedule
from models.task import TaskRun
from schemas.playbook import PlaybookScheduleCreate, PlaybookScheduleUpdate
from services import ansible_runner
from services.schedule_targets import schedule_out


class ScheduledOnlineTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.session()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.group = HostGroup(id=uuid.uuid4(), name="room")
        self.tag = HostTag(id=uuid.uuid4(), name="lab")
        self.repo = PlaybookRepo(id=uuid.uuid4(), name="repo", git_url="", local_path="")
        self.a = Host(id=uuid.uuid4(), hostname="A", os=HostOS.windows_11, status=HostStatus.online, group=self.group)
        self.b = Host(id=uuid.uuid4(), hostname="B", os=HostOS.windows_11, status=HostStatus.offline, group=self.group)
        self.c = Host(id=uuid.uuid4(), hostname="C", os=HostOS.windows_11, status=HostStatus.online, tag_id=self.tag.id)
        self.schedule = PlaybookSchedule(id=uuid.uuid4(), repo_id=self.repo.id, playbook_name="test.yml",
            host_group_ids=[str(self.group.id)], host_ids=[str(self.a.id)], host_tag_ids=[str(self.tag.id)],
            cron_expression="* * * * *", enabled=True, only_online=True)
        self.db.add_all([self.group, self.tag, self.repo, self.a, self.b, self.c, self.schedule])
        self.db.commit()
        self.reachable = {"A", "C"}

    def dispatch(self):
        with mock.patch.object(ansible_runner, "SessionLocal", self.session), \
             mock.patch.object(ansible_runner, "schedule_is_due", return_value=True), \
             mock.patch.object(ansible_runner, "schedule_host_reachable", side_effect=lambda host, port: host in self.reachable), \
             mock.patch.object(ansible_runner.run_playbook_task, "delay") as enqueue:
            ansible_runner.dispatch_scheduled_playbooks.run()
        self.db.expire_all()
        return enqueue.call_count

    def test_status_and_group_members_are_resolved_at_each_dispatch(self):
        self.assertEqual(self.dispatch(), 1)
        self.assertEqual(set(self.db.query(TaskRun).all()[0].host_ids), {str(self.a.id), str(self.c.id)})
        # Stale database status must not exclude a newly reachable PC.
        self.reachable = {"B"}
        self.assertEqual(self.dispatch(), 1)
        tasks = self.db.query(TaskRun).order_by(TaskRun.created_at, TaskRun.id).all()
        self.assertIn([str(self.b.id)], [task.host_ids for task in tasks])

    def test_all_offline_skips_dispatch(self):
        self.reachable = set()
        self.assertEqual(self.dispatch(), 0)
        self.assertEqual(self.db.query(TaskRun).count(), 0)

    def test_disabled_filter_keeps_offline_hosts(self):
        self.schedule.only_online = False
        self.db.commit()
        self.assertEqual(self.dispatch(), 1)
        self.assertEqual(set(self.db.query(TaskRun).one().host_ids), {str(self.a.id), str(self.b.id), str(self.c.id)})

    def test_api_exposes_and_preserves_the_condition(self):
        request = PlaybookScheduleCreate(repo_id=self.repo.id, playbook_name="test.yml",
            cron_expression="* * * * *", only_online=True)
        self.assertTrue(request.only_online)
        self.assertFalse(PlaybookScheduleCreate(repo_id=self.repo.id, playbook_name="test.yml",
            cron_expression="* * * * *").only_online)
        self.assertEqual(PlaybookScheduleUpdate(only_online=False).model_dump(exclude_unset=True), {"only_online": False})
        self.assertTrue(schedule_out(self.schedule).only_online)


class ScheduledProbeTests(unittest.TestCase):
    def test_ssh_connection_failure_is_offline(self):
        with mock.patch.object(ansible_runner.socket, "create_connection", side_effect=TimeoutError):
            self.assertFalse(ansible_runner.schedule_host_reachable("10.0.0.1", 22))

    def test_open_ssh_port_is_online(self):
        with mock.patch.object(ansible_runner.socket, "create_connection") as connect:
            self.assertTrue(ansible_runner.schedule_host_reachable("10.0.0.1", 5022))
            connect.assert_called_once_with(("10.0.0.1", 5022), timeout=2)
