import unittest
import uuid
from unittest import mock

from models.task import TaskStatus, TaskType
from services import waiting_tasks


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


class CreateTaskRunsTests(unittest.TestCase):
    def _create(self, task_type=TaskType.playbook, defer=True, hosts=(ONLINE, OFFLINE_1, OFFLINE_2), steps=None, **fields):
        db = _FakeDb()
        online = [h for h in hosts if h == ONLINE]
        offline = [h for h in hosts if h != ONLINE]
        with mock.patch.object(waiting_tasks, "split_offline", return_value=(online, offline)) as split,                 mock.patch.object(waiting_tasks, "_supersede") as supersede:
            now_tasks, waiting = waiting_tasks.create_task_sequence(
                db, task_type=task_type, host_ids=list(hosts), created_by=None, defer_offline=defer, steps=steps or [fields]
            )
        return db, split, supersede, now_tasks, waiting

    def test_offline_hosts_share_one_waiting_task(self):
        db, _, _, now_tasks, waiting = self._create(playbook_name="install_7zip.yaml", extra_vars={"a": 1})
        self.assertEqual([t.host_ids for t in now_tasks], [[ONLINE]])
        self.assertEqual(now_tasks[0].status, TaskStatus.queued)
        self.assertEqual(len(waiting), 1)
        task = waiting[0]
        self.assertEqual(task.host_ids, [OFFLINE_1, OFFLINE_2])
        self.assertEqual(task.ready_host_ids, [])
        self.assertEqual(task.status, TaskStatus.waiting)
        self.assertEqual(task.playbook_name, "install_7zip.yaml")
        self.assertEqual(task.extra_vars, {"a": 1})
        self.assertIn("ПК не в сети: 2", task.log_output)
        self.assertEqual(len(db.added), 2)

    def test_all_hosts_offline_means_no_immediate_task(self):
        _, _, _, now_tasks, waiting = self._create(hosts=(OFFLINE_1,))
        self.assertEqual(now_tasks, [])
        self.assertEqual(len(waiting), 1)

    def test_defer_off_keeps_the_old_behaviour(self):
        _, split, supersede, now_tasks, waiting = self._create(defer=False)
        split.assert_not_called()
        supersede.assert_not_called()
        self.assertEqual(now_tasks[0].host_ids, [ONLINE, OFFLINE_1, OFFLINE_2])
        self.assertEqual(waiting, [])

    def test_diagnostics_are_never_deferred(self):
        _, split, _, now_tasks, waiting = self._create(task_type=TaskType.host_diagnostic)
        split.assert_not_called()
        self.assertEqual(len(now_tasks[0].host_ids), 3)
        self.assertEqual(waiting, [])

    def test_reassignment_takes_hosts_from_older_waiting_tasks(self):
        _, _, supersede, _, _ = self._create(repo_id="r", playbook_name="a.yml")
        supersede.assert_called_once()
        _db, task_type, hosts, fields = supersede.call_args.args
        self.assertEqual((task_type, hosts, fields), (TaskType.playbook, [ONLINE, OFFLINE_1, OFFLINE_2], {"repo_id": "r", "playbook_name": "a.yml"}))

    def test_several_playbooks_run_one_after_another(self):
        steps = [{"playbook_name": "a.yml"}, {"playbook_name": "b.yml"}, {"playbook_name": "c.yml"}]
        _, _, supersede, now_tasks, waiting = self._create(steps=steps)
        self.assertEqual(supersede.call_count, 3)
        self.assertEqual([t.playbook_name for t in now_tasks], ["a.yml", "b.yml", "c.yml"])
        self.assertEqual([t.status for t in now_tasks], [TaskStatus.queued, TaskStatus.pending, TaskStatus.pending])
        self.assertEqual([t.after_task_id for t in now_tasks], [None, now_tasks[0].id, now_tasks[1].id])
        self.assertEqual([t.status for t in waiting], [TaskStatus.waiting] * 3)
        self.assertEqual([t.after_task_id for t in waiting], [None, waiting[0].id, waiting[1].id])

    def test_single_task_wrapper(self):
        db = _FakeDb()
        with mock.patch.object(waiting_tasks, "split_offline", return_value=([], [OFFLINE_1])),                 mock.patch.object(waiting_tasks, "_supersede"):
            now_task, waiting = waiting_tasks.create_task_runs(db, task_type=TaskType.software_scan, host_ids=[OFFLINE_1], created_by=None)
        self.assertIsNone(now_task)
        self.assertEqual(waiting.host_ids, [OFFLINE_1])


class DispatchTests(unittest.TestCase):
    def test_every_deferrable_type_has_a_celery_task(self):
        for task_type in waiting_tasks.DEFERRABLE_TYPES:
            self.assertTrue(hasattr(waiting_tasks._celery_task(task_type), "apply_async"), task_type)

    def test_other_types_are_rejected(self):
        with self.assertRaises(ValueError):
            waiting_tasks._celery_task(TaskType.host_diagnostic)


if __name__ == "__main__":
    unittest.main()
