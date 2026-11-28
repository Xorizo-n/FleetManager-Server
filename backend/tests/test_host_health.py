import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services import host_health


class HostHealthTests(unittest.TestCase):
    @patch.object(host_health, "_ping_hosts")
    @patch.object(host_health.redis.Redis, "from_url")
    def test_duplicate_check_skips_database_and_ansible(self, redis_client, check):
        redis_client.return_value.lock.return_value.acquire.return_value = False
        host_health.ping_hosts()
        check.assert_not_called()

    @patch.object(host_health, "_ping_hosts", side_effect=RuntimeError("check failed"))
    @patch.object(host_health.redis.Redis, "from_url")
    def test_lock_is_released_on_failure(self, redis_client, check):
        lock = redis_client.return_value.lock.return_value
        with self.assertRaises(RuntimeError):
            host_health.ping_hosts()
        lock.release.assert_called_once()

    @patch.object(host_health, "build_full_inventory", return_value={})
    @patch.object(host_health, "run_ansible")
    @patch.object(host_health, "SessionLocal")
    def test_timeout_without_host_results_does_not_update_status(self, session, runner, inventory):
        db = session.return_value
        host = SimpleNamespace(id="host")
        db.query.return_value.all.return_value = [host]
        runner.return_value = SimpleNamespace(status="timeout", rc=254, stats={}, events=[])
        host_health._ping_hosts()
        db.execute.assert_not_called()
        db.add_all.assert_not_called()
        db.commit.assert_not_called()
        db.close.assert_called_once()
        self.assertEqual(runner.call_args.kwargs["timeout"], host_health.CHECK_TIMEOUT)

    @patch.object(host_health, "release_waiting_tasks")
    @patch.object(host_health, "HostStatusHistory")
    @patch.object(host_health, "build_full_inventory", return_value={})
    @patch.object(host_health, "run_ansible")
    @patch.object(host_health, "SessionLocal")
    def test_timeout_saves_confirmed_results_only(self, session, runner, inventory, history, release):
        db = session.return_value
        db.query.return_value.all.return_value = [
            SimpleNamespace(id=host) for host in ("online", "offline", "failed", "untested", "newer")
        ]
        runner.return_value = SimpleNamespace(status="timeout", rc=254, stats={}, events=[
            {"event": "runner_on_ok", "event_data": {"host": "online", "res": {"rc": 0}}},
            {"event": "runner_on_unreachable", "event_data": {"host": "offline"}},
            {"event": "runner_on_failed", "event_data": {"host": "failed"}},
            {"event": "runner_on_unreachable", "event_data": {"host": "newer"}},
            {"event": "runner_on_start", "event_data": {"host": "untested"}},
            {"event": "runner_on_unreachable", "event_data": {"host": "unexpected"}},
        ])
        result = db.execute.return_value.scalars.return_value
        result.all.side_effect = [["online"], ["offline", "failed"]]

        host_health._ping_hosts()

        updates = [call.args[0].compile().params for call in db.execute.call_args_list]
        self.assertEqual(updates[0]["id_1"], ["online"])
        self.assertEqual(updates[1]["id_1"], ["offline", "failed", "newer"])
        self.assertLessEqual(updates[1]["last_checked_at_1"], updates[1]["last_checked_at"])
        self.assertEqual(
            [(call.kwargs["host_id"], call.kwargs["status"]) for call in history.call_args_list],
            [("online", host_health.HostStatus.online),
             ("offline", host_health.HostStatus.offline), ("failed", host_health.HostStatus.offline)],
        )
        release.assert_called_once_with(db, "online", reason="проверка по SSH")
        db.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
