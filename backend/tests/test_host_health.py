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
    def test_timeout_discards_partial_results(self, session, runner, inventory):
        db = session.return_value
        host = SimpleNamespace(id="host")
        db.query.return_value.all.return_value = [host]
        runner.return_value = SimpleNamespace(status="timeout", rc=254, stats={})
        host_health._ping_hosts()
        db.add.assert_not_called()
        db.commit.assert_not_called()
        db.close.assert_called_once()
        self.assertEqual(runner.call_args.kwargs["timeout"], host_health.CHECK_TIMEOUT)

    @patch.object(host_health, "release_waiting_tasks")
    @patch.object(host_health, "HostStatusHistory")
    @patch.object(host_health, "build_full_inventory", return_value={})
    @patch.object(host_health, "run_ansible")
    @patch.object(host_health, "SessionLocal")
    def test_complete_run_with_unreachable_host_updates_status(self, session, runner, inventory, history, release):
        db = session.return_value
        host = SimpleNamespace(id="host")
        db.query.return_value.all.return_value = [host]
        runner.return_value = SimpleNamespace(status="failed", rc=4, stats={"dark": {"host": 1}}, events=[])
        host_health._ping_hosts()
        self.assertEqual(host.status, host_health.HostStatus.offline)
        db.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
