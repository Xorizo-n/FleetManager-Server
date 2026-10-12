import threading
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

from sqlalchemy.dialects import postgresql

from services import host_parallel
from services.host_parallel import HostOutcome, run_for_hosts


class _Session:
    def __init__(self, hosts):
        self.hosts = hosts

    def get(self, _model, host_id):
        return self.hosts.get(host_id)

    def rollback(self):
        pass

    def close(self):
        pass


class RunForHostsTests(unittest.TestCase):
    def setUp(self):
        self.hosts = {}
        for i in range(12):
            host_id = uuid.uuid4()
            self.hosts[host_id] = SimpleNamespace(id=host_id, hostname=f"SU5-K204-W{i:02d}", ip_address=None)
        self.ids = list(self.hosts)
        self.logs = []
        patcher = mock.patch.object(host_parallel, "append_task_log", side_effect=lambda _db, _task, line: self.logs.append(line))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_hosts(self, worker, **kwargs):
        return run_for_hosts("task", self.ids, worker, session_factory=lambda: _Session(self.hosts), **kwargs)

    def test_hosts_run_side_by_side_but_not_more_than_the_limit(self):
        active, peak, lock = 0, 0, threading.Lock()

        def worker(_db, _host):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.1)
            with lock:
                active -= 1
            return HostOutcome.ok

        started = time.monotonic()
        failed = self.run_hosts(worker, parallelism=4)

        self.assertFalse(failed)
        self.assertEqual(peak, 4)
        self.assertLess(time.monotonic() - started, 0.12 * 12 / 2)  # sequentially it would be 1.2 s

    def test_every_host_is_processed_once(self):
        seen = []
        self.run_hosts(lambda _db, host: seen.append(host.hostname) or HostOutcome.ok, parallelism=5)
        self.assertEqual(sorted(seen), sorted(h.hostname for h in self.hosts.values()))

    def test_failed_canary_leaves_the_other_hosts_alone(self):
        seen = []
        failed = self.run_hosts(lambda _db, host: seen.append(host) or HostOutcome.failed, canary=True)

        self.assertTrue(failed)
        self.assertEqual(len(seen), 1)
        self.assertIn("остальные (11) не тронуты", self.logs[-1])

    def test_unreachable_hosts_do_not_count_as_the_canary(self):
        outcomes = iter([HostOutcome.unreachable, HostOutcome.unreachable] + [HostOutcome.ok] * 10)
        lock = threading.Lock()

        def worker(_db, _host):
            with lock:
                return next(outcomes)

        failed = self.run_hosts(worker, canary=True)
        self.assertTrue(failed)  # the unreachable hosts still make the task unsuccessful
        self.assertEqual(next(outcomes, "done"), "done")  # everyone else was updated

    def test_worker_exception_is_logged_against_the_host(self):
        def worker(_db, host):
            if host.hostname.endswith("03"):
                raise RuntimeError("Ansible: timed out")
            return HostOutcome.ok

        self.assertTrue(self.run_hosts(worker))
        self.assertIn("[SU5-K204-W03] ОШИБКА: Ansible: timed out", self.logs)


class AppendTaskLogTests(unittest.TestCase):
    def test_log_is_appended_by_the_database_not_overwritten(self):
        executed = []
        db = SimpleNamespace(execute=executed.append, commit=lambda: None)
        host_parallel.append_task_log(db, uuid.uuid4(), "[PC] ok")
        sql = str(executed[0].compile(dialect=postgresql.dialect()))
        self.assertIn("UPDATE task_runs SET log_output=CASE", sql)
        self.assertIn("task_runs.log_output ||", sql)


if __name__ == "__main__":
    unittest.main()
