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
    def _create(self, task_type=TaskType.playbook, defer=True, hosts=(ONLINE, OFFLINE_1, OFFLINE_2), existing=None, **fields):
        db = _FakeDb()
        online = [h for h in hosts if h == ONLINE]
        offline = [h for h in hosts if h != ONLINE]
        with mock.patch.object(waiting_tasks, "split_offline", return_value=(online, offline)) as split, \
                mock.patch.object(waiting_tasks, "_existing_waiting", side_effect=lambda _db, _t, host, _f: (existing or {}).get(host)):
            now_task, waiting = waiting_tasks.create_task_runs(
                db, task_type=task_type, host_ids=list(hosts), created_by=None, defer_offline=defer, **fields
            )
        return db, split, now_task, waiting

    def test_offline_hosts_get_their_own_waiting_tasks(self):
        db, _, now_task, waiting = self._create(playbook_name="install_7zip.yaml", extra_vars={"a": 1})
        self.assertEqual(now_task.host_ids, [ONLINE])
        self.assertEqual(now_task.status, TaskStatus.queued)
        self.assertEqual([task.host_ids for task in waiting], [[OFFLINE_1], [OFFLINE_2]])
        for task in waiting:
            self.assertEqual(task.status, TaskStatus.waiting)
            self.assertEqual(task.playbook_name, "install_7zip.yaml")
            self.assertEqual(task.extra_vars, {"a": 1})
            self.assertIn("ПК не в сети", task.log_output)
        self.assertEqual(len(db.added), 3)

    def test_all_hosts_offline_means_no_immediate_task(self):
        _, _, now_task, waiting = self._create(hosts=(OFFLINE_1,))
        self.assertIsNone(now_task)
        self.assertEqual(len(waiting), 1)

    def test_defer_off_keeps_the_old_behaviour(self):
        _, split, now_task, waiting = self._create(defer=False)
        split.assert_not_called()
        self.assertEqual(now_task.host_ids, [ONLINE, OFFLINE_1, OFFLINE_2])
        self.assertEqual(waiting, [])

    def test_diagnostics_are_never_deferred(self):
        _, split, now_task, waiting = self._create(task_type=TaskType.host_diagnostic)
        split.assert_not_called()
        self.assertEqual(len(now_task.host_ids), 3)
        self.assertEqual(waiting, [])

    def test_the_same_waiting_task_is_not_duplicated(self):
        already = mock.Mock(host_ids=[OFFLINE_1], status=TaskStatus.waiting)
        db, _, _, waiting = self._create(existing={OFFLINE_1: already})
        self.assertIs(waiting[0], already)
        self.assertEqual(len(db.added), 2)  # задача для ПК в сети + новая ожидающая для OFFLINE_2


class DispatchTests(unittest.TestCase):
    def test_every_deferrable_type_has_a_celery_task(self):
        for task_type in waiting_tasks.DEFERRABLE_TYPES:
            self.assertTrue(hasattr(waiting_tasks._celery_task(task_type), "apply_async"), task_type)

    def test_other_types_are_rejected(self):
        with self.assertRaises(ValueError):
            waiting_tasks._celery_task(TaskType.host_diagnostic)


if __name__ == "__main__":
    unittest.main()
