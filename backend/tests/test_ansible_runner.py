import sys
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

from models.task import TaskStatus
from services import ansible_runner
from services.ansible_runner import playbook_matched_hosts


class _Result:
    def __init__(self, rc, stats):
        self.rc = rc
        self.stats = stats


class AnsibleRunnerTests(unittest.TestCase):
    def test_clean_run_without_matching_hosts_is_not_successful(self):
        self.assertFalse(playbook_matched_hosts(_Result(0, {}), {"host-1"}))

    def test_clean_run_with_selected_host_is_successful(self):
        self.assertTrue(playbook_matched_hosts(_Result(0, {}), {"host-1"}, {"host-1"}))

    def test_nonzero_return_code_is_failure(self):
        self.assertFalse(playbook_matched_hosts(_Result(2, {"host-1": {}}), {"host-1"}))

    def test_runner_defaults_to_configured_timeout_and_preserves_explicit_timeout(self):
        runner = Mock(return_value=SimpleNamespace(rc=0, status="successful", stats={}, events=[]))
        with patch.dict(sys.modules, {"ansible_runner": SimpleNamespace(run=runner)}), \
                patch.object(ansible_runner.settings, "ansible_job_timeout_seconds", 123):
            ansible_runner.run_ansible()
            self.assertEqual(runner.call_args.kwargs["timeout"], 123)
            ansible_runner.run_ansible(timeout=10)
            self.assertEqual(runner.call_args.kwargs["timeout"], 10)

    def test_raw_command_timeout_does_not_return_empty_output(self):
        with patch.object(ansible_runner, "run_ansible", return_value=SimpleNamespace(status="timeout", events=[])):
            with self.assertRaises(TimeoutError):
                ansible_runner.run_raw_command({}, "host-1", "hostname")

    def test_playbook_timeout_keeps_log_and_finishes_as_failed(self):
        host = str(uuid.uuid4())
        task = SimpleNamespace(repo_id=uuid.uuid4(), run_as_user_id=None, created_by=None, host_ids=[host],
                               playbook_name="example.yml", extra_vars={})
        db = Mock()
        db.get.side_effect = [task, SimpleNamespace(local_path="/playbooks")]
        db.query.return_value.filter.return_value = []

        def time_out(**kwargs):
            kwargs["event_handler"]({"stdout": "TASK [Waiting for host]"})
            return SimpleNamespace(rc=254, status="timeout", stats={})

        with patch.object(ansible_runner, "SessionLocal", return_value=db), \
                patch.object(ansible_runner.run_as, "plan"), \
                patch.object(ansible_runner.run_as, "log_lines", return_value=[]), \
                patch.object(ansible_runner, "build_full_inventory", return_value={}), \
                patch.object(ansible_runner, "run_ansible", side_effect=time_out), \
                patch.object(ansible_runner.settings, "ansible_job_timeout_seconds", 123):
            ansible_runner.run_playbook_task.run(str(uuid.uuid4()))

        self.assertEqual(task.status, TaskStatus.failed)
        self.assertEqual(task.host_states, {host: "failed"})
        self.assertIsNotNone(task.finished_at)
        self.assertIn("TASK [Waiting for host]", task.log_output)
        self.assertIn("тайм-ауту (123 с)", task.log_output)
        db.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
