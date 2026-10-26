import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

from models.task import TaskStatus, TaskType
from services import waiting_tasks
from services.ansible_runner import host_outcomes, recap_from_log


class _FakeDb:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, obj):
        if obj.id is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def refresh(self, _obj):
        pass


ONLINE = str(uuid.uuid4())
OFFLINE_1 = str(uuid.uuid4())
OFFLINE_2 = str(uuid.uuid4())


class CreateTaskSequenceTests(unittest.TestCase):
    def _create(self, task_type=TaskType.playbook, defer=True, hosts=(ONLINE, OFFLINE_1, OFFLINE_2), steps=None, **fields):
        db = _FakeDb()
        online = [h for h in hosts if h == ONLINE]
        offline = [h for h in hosts if h != ONLINE]
        with mock.patch.object(waiting_tasks, "split_offline", return_value=(online, offline)) as split, \
                mock.patch.object(waiting_tasks, "_supersede") as supersede:
            groups, execution = waiting_tasks.create_task_sequence(
                db, task_type=task_type, host_ids=list(hosts), created_by=None, defer_offline=defer, steps=steps or [fields]
            )
        return db, split, supersede, groups, execution

    def test_one_launch_holds_every_host(self):
        db, _, _, groups, execution = self._create(playbook_name="install_7zip.yaml", extra_vars={"a": 1})
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertTrue(group.grouped)
        self.assertEqual(group.host_ids, [ONLINE, OFFLINE_1, OFFLINE_2])
        self.assertEqual(group.host_states, {ONLINE: "queued", OFFLINE_1: "waiting", OFFLINE_2: "waiting"})
        self.assertEqual(group.status, TaskStatus.queued)
        self.assertIn("Не в сети: 2", group.log_output)
        # Выполняет дочерняя задача, и только для ПК в сети
        self.assertEqual(execution.parent_id, group.id)
        self.assertEqual(execution.host_ids, [ONLINE])
        self.assertEqual((execution.playbook_name, execution.extra_vars), ("install_7zip.yaml", {"a": 1}))
        self.assertEqual(len(db.added), 2)

    def test_all_hosts_offline_means_nothing_to_run_now(self):
        _, _, _, groups, execution = self._create(hosts=(OFFLINE_1,))
        self.assertIsNone(execution)
        self.assertEqual(groups[0].status, TaskStatus.waiting)

    def test_defer_off_runs_everything_now(self):
        _, split, supersede, groups, execution = self._create(defer=False)
        split.assert_not_called()
        supersede.assert_not_called()
        self.assertEqual(execution.host_ids, [ONLINE, OFFLINE_1, OFFLINE_2])
        self.assertEqual(set(groups[0].host_states.values()), {"queued"})

    def test_diagnostics_are_never_deferred(self):
        _, split, _, _, execution = self._create(task_type=TaskType.host_diagnostic)
        split.assert_not_called()
        self.assertEqual(len(execution.host_ids), 3)

    def test_reassignment_cancels_older_waiting(self):
        _, _, supersede, _, _ = self._create(repo_id="r", playbook_name="a.yml")
        _db, task_type, hosts, fields = supersede.call_args.args
        self.assertEqual((task_type, hosts, fields), (TaskType.playbook, [ONLINE, OFFLINE_1, OFFLINE_2], {"repo_id": "r", "playbook_name": "a.yml"}))

    def test_several_playbooks_run_one_after_another(self):
        steps = [{"playbook_name": "a.yml"}, {"playbook_name": "b.yml"}, {"playbook_name": "c.yml"}]
        db, _, supersede, groups, execution = self._create(steps=steps)
        self.assertEqual(supersede.call_count, 3)
        self.assertEqual([g.playbook_name for g in groups], ["a.yml", "b.yml", "c.yml"])
        self.assertEqual([g.after_task_id for g in groups], [None, groups[0].id, groups[1].id])
        self.assertEqual([g.host_states[ONLINE] for g in groups], ["queued", "pending", "pending"])
        executions = [t for t in db.added if not t.grouped]
        self.assertIs(executions[0], execution)
        self.assertEqual([e.status for e in executions], [TaskStatus.queued, TaskStatus.pending, TaskStatus.pending])
        self.assertEqual([e.after_task_id for e in executions], [None, executions[0].id, executions[1].id])
        self.assertEqual([e.parent_id for e in executions], [g.id for g in groups])


class GroupStatusTests(unittest.TestCase):
    def test_what_is_still_going_wins(self):
        status = waiting_tasks._group_status
        self.assertEqual(status({"a": "success", "b": "running", "c": "waiting"}), TaskStatus.running)
        self.assertEqual(status({"a": "failed", "b": "ready"}), TaskStatus.queued)
        self.assertEqual(status({"a": "success", "b": "waiting"}), TaskStatus.waiting)
        self.assertEqual(status({"a": "success", "b": "pending"}), TaskStatus.pending)
        self.assertEqual(status({"a": "waiting", "b": "pending"}), TaskStatus.pending)
        self.assertEqual(status({"a": "success", "b": "failed", "c": "cancelled"}), TaskStatus.failed)
        self.assertEqual(status({"a": "success", "b": "cancelled"}), TaskStatus.success)
        self.assertEqual(status({"a": "cancelled"}), TaskStatus.cancelled)

    def test_finished_when_nothing_is_open(self):
        group = SimpleNamespace(host_states={"a": "running"}, status=None, started_at=None, finished_at=None)
        waiting_tasks._set_states(group, {"a": "success"})
        self.assertEqual(group.status, TaskStatus.success)
        self.assertIsNotNone(group.finished_at)


class HostResultsTests(unittest.TestCase):
    def test_executor_states_win_over_task_status(self):
        execution = SimpleNamespace(host_ids=["a", "b", "c"], status=TaskStatus.failed, host_states={"a": "success", "b": "failed"})
        self.assertEqual(waiting_tasks.host_results(execution), {"a": "success", "b": "failed", "c": "failed"})

    def test_playbook_recap_per_host(self):
        result = SimpleNamespace(stats={"processed": {"a": 1, "b": 1, "c": 1}, "failures": {"b": 1}, "dark": {"c": 1}})
        self.assertEqual(host_outcomes(result, {"a", "b", "c", "d"}, trusted=True, fallback=TaskStatus.failed),
                         {"a": "success", "b": "failed", "c": "failed", "d": "failed"})

    def test_no_recap_means_task_status_for_all(self):
        result = SimpleNamespace(stats={"processed": {"a": 1}})
        self.assertEqual(host_outcomes(result, {"a", "b"}, trusted=False, fallback=TaskStatus.failed), {"a": "failed", "b": "failed"})

    LOG = (
        "[Fleet Manager] Выполняется от учётки установки агента\n"
        "TASK [Check] ****\nok: [a]\nfatal: [b]: FAILED! => {}\n\n"
        "PLAY RECAP *********************************************************************\n"
        "a                          : ok=4    changed=1    unreachable=0    failed=0    skipped=3    rescued=0    ignored=0   \n"
        "\x1b[0;31mb\x1b[0m                          : ok=1    changed=0    unreachable=0    failed=1    skipped=0    rescued=0    ignored=1   \n"
        "c                          : ok=0    changed=0    unreachable=1    failed=0    skipped=0    rescued=0    ignored=0   \n"
    )

    def test_recap_from_the_log_when_stats_are_lost(self):
        # Long runs: playbook_on_stats sometimes misses result.stats although the recap is printed
        result = SimpleNamespace(stats=None)
        self.assertEqual(host_outcomes(result, {"a", "b", "c", "d"}, trusted=True, fallback=TaskStatus.failed, log_text=self.LOG),
                         {"a": "success", "b": "failed", "c": "failed", "d": "failed"})

    def test_stats_win_over_the_log(self):
        result = SimpleNamespace(stats={"processed": {"a": 1, "b": 1}, "failures": {"a": 1}})
        self.assertEqual(host_outcomes(result, {"a", "b"}, trusted=True, fallback=TaskStatus.failed, log_text=self.LOG),
                         {"a": "failed", "b": "success"})

    def test_untrusted_run_ignores_the_log(self):
        self.assertEqual(host_outcomes(SimpleNamespace(stats=None), {"a"}, trusted=False, fallback=TaskStatus.failed, log_text=self.LOG),
                         {"a": "failed"})

    def test_recap_parsing(self):
        self.assertEqual(recap_from_log(self.LOG), {"a": True, "b": False, "c": False})
        self.assertEqual(recap_from_log("no recap here"), {})
        self.assertEqual(recap_from_log(None), {})


class DispatchTests(unittest.TestCase):
    def test_every_deferrable_type_has_a_celery_task(self):
        for task_type in waiting_tasks.DEFERRABLE_TYPES:
            task = waiting_tasks._celery_task(task_type)
            self.assertEqual(task.name, waiting_tasks._EXECUTORS[task_type])

    def test_other_types_are_rejected(self):
        with self.assertRaises(ValueError):
            waiting_tasks._celery_task(TaskType.host_diagnostic)


if __name__ == "__main__":
    unittest.main()
