import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from database import get_db
from dependencies import get_current_user
from models.user import UserRole
from models.host import HostStatus
from models.task import TaskStatus, TaskType
from routers.hosts import restart_hosts, router
from schemas.host import HostRestartRequest
from services.host_parallel import HostOutcome
from services.host_restart import RESTART_COMMAND, restart_host


def host(status=HostStatus.online, power_state=None):
    return SimpleNamespace(id=uuid.uuid4(), hostname="SU5-D203-W01", ip_address="10.0.0.1", status=status, power_state=power_state)


class RestartWorkerTests(unittest.TestCase):
    def test_command_requests_normal_restart_without_force(self):
        self.assertIn("shutdown.exe /r /t 0", RESTART_COMMAND)
        self.assertNotIn("/f", RESTART_COMMAND.lower())

    @patch("services.host_restart.append_task_log")
    @patch("services.host_restart.run_raw_command")
    def test_windows_acceptance_is_reported_without_claiming_completed_reboot(self, run, log):
        run.return_value = "FLEET_RESTART_ACCEPTED"
        result = restart_host(MagicMock(), uuid.uuid4(), {}, host())
        self.assertEqual(result, HostOutcome.ok)
        self.assertIn("завершение перезагрузки не проверялось", log.call_args.args[2])
        run.assert_called_once()

    @patch("services.host_restart.append_task_log")
    @patch("services.host_restart.run_raw_command")
    def test_offline_and_updates_are_not_restarted(self, run, log):
        self.assertEqual(restart_host(MagicMock(), uuid.uuid4(), {}, host(HostStatus.offline)), HostOutcome.unreachable)
        updating = {"updates_installing": True, "reported_at": datetime.now(timezone.utc).isoformat()}
        self.assertEqual(restart_host(MagicMock(), uuid.uuid4(), {}, host(power_state=updating)), HostOutcome.failed)
        run.assert_not_called()

    @patch("services.host_restart.append_task_log")
    @patch("services.host_restart.run_raw_command", side_effect=RuntimeError("disconnected"))
    def test_disconnect_is_uncertain_and_never_retried(self, run, log):
        self.assertEqual(restart_host(MagicMock(), uuid.uuid4(), {}, host()), HostOutcome.failed)
        self.assertIn("мог начать перезагрузку", log.call_args.args[2])
        run.assert_called_once()

    @patch("services.host_restart.append_task_log")
    @patch("services.host_restart.run_raw_command", return_value="unexpected")
    def test_missing_marker_is_not_a_success(self, run, log):
        self.assertEqual(restart_host(MagicMock(), uuid.uuid4(), {}, host()), HostOutcome.failed)


class RestartApiTests(unittest.TestCase):
    def make_db(self, hosts):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = hosts
        return db

    @patch("routers.hosts.record_audit")
    @patch("routers.hosts.run_host_restart.delay")
    def test_online_hosts_are_queued_once(self, delay, audit):
        pc = host(); db = self.make_db([pc]); user = SimpleNamespace(id=uuid.uuid4())
        def add(task): task.id = uuid.uuid4()
        db.add.side_effect = add
        task = restart_hosts(HostRestartRequest(host_ids=[pc.id, pc.id]), MagicMock(), db, user)
        self.assertEqual(task.task_type, TaskType.host_restart)
        self.assertEqual(task.status, TaskStatus.queued)
        self.assertEqual(task.host_ids, [str(pc.id)])
        delay.assert_called_once_with(str(task.id))
        audit.assert_called_once()

    def test_viewer_cannot_restart(self):
        app = FastAPI(); app.include_router(router)
        app.dependency_overrides[get_db] = lambda: MagicMock()
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4(), role=UserRole.viewer)
        with patch("routers.hosts.run_host_restart.delay") as delay:
            response = TestClient(app).post("/hosts/restart", json={"host_ids": [str(uuid.uuid4())]})
        self.assertEqual(response.status_code, 403)
        delay.assert_not_called()

    @patch("routers.hosts.run_host_restart.delay")
    def test_offline_or_missing_host_is_rejected(self, delay):
        pc = host(HostStatus.offline)
        with self.assertRaises(HTTPException) as exc:
            restart_hosts(HostRestartRequest(host_ids=[pc.id]), MagicMock(), self.make_db([pc]), SimpleNamespace(id=uuid.uuid4()))
        self.assertEqual(exc.exception.status_code, 409)
        with self.assertRaises(HTTPException) as exc:
            restart_hosts(HostRestartRequest(host_ids=[pc.id]), MagicMock(), self.make_db([]), SimpleNamespace(id=uuid.uuid4()))
        self.assertEqual(exc.exception.status_code, 404)
        delay.assert_not_called()


if __name__ == "__main__": unittest.main()
