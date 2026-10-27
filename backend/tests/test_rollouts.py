"""Software rollout tracker: requests with items, linked playbook runs, replace-on-update."""

import unittest
import uuid
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.rollout import RolloutItem, RolloutItemStatus, RolloutRequest, RolloutStatus
from models.task import TaskRun, TaskStatus, TaskType
from models.user import User, UserRole
from routers.rollouts import create_rollout, delete_rollout, list_assignees, list_rollouts, task_progress, update_rollout
from schemas.rollout import RolloutItemIn, RolloutRequestCreate, RolloutRequestUpdate


class SchemaTests(unittest.TestCase):
    def test_blank_text_becomes_none_and_course_is_required(self):
        item = RolloutItemIn(software=" Git 2.55 ", rooms="  ", note="")
        self.assertEqual((item.software, item.rooms, item.note), ("Git 2.55", None, None))
        with self.assertRaises(ValidationError):
            RolloutRequestCreate(course="   ")

    def test_progress_counts_ready_as_waiting(self):
        task = TaskRun(task_type=TaskType.playbook, status=TaskStatus.waiting, host_ids=["a", "b", "c", "d"],
                       host_states={"a": "success", "b": "ready", "c": "waiting", "d": "failed"}, playbook_name="p.yml")
        self.assertEqual(task_progress(task).host_states, {"success": 1, "waiting": 2, "failed": 1})

    def test_progress_of_task_without_host_states(self):
        task = TaskRun(task_type=TaskType.playbook, status=TaskStatus.success, host_ids=["a", "b"])
        self.assertEqual(task_progress(task).host_states, {"success": 2})


class RolloutDbTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.operator = self.user("d.d.kozlov", UserRole.operator, display_name="Козлов Д.")
        self.viewer = self.user("viewer", UserRole.viewer)
        self.user("old.admin", UserRole.admin, is_active=False)
        self.task = TaskRun(id=uuid.uuid4(), task_type=TaskType.playbook, status=TaskStatus.waiting, host_ids=["h1", "h2"],
                            host_states={"h1": "success", "h2": "waiting"}, playbook_name="playbooks/install/install_1c_platform.yml")
        self.db.add(self.task)
        self.db.commit()

    def user(self, name, role, **values):
        user = User(id=uuid.uuid4(), username=name, email=f"{name}@example.org", password_hash="x", role=role, **values)
        self.db.add(user)
        self.db.flush()
        return user

    def create(self):
        return create_rollout(
            RolloutRequestCreate(
                partner="1С", course="Разработка на бизнес-ориентированных языках", rooms="K-103", schedule="Вторник 3 пара",
                assignee_id=self.operator.id,
                items=[
                    RolloutItemIn(software="1С 8.3.27 клиент", status=RolloutItemStatus.in_progress, task_run_id=self.task.id),
                    RolloutItemIn(software="Сервер 1С", rooms="K-103-OP", status=RolloutItemStatus.blocked, note="нет 64-битного дистрибутива"),
                ],
            ),
            None, self.db, self.operator,
        )

    def test_create_lists_items_in_order_with_names_and_task_progress(self):
        created = self.create()
        self.assertEqual(created.status, RolloutStatus.new)
        self.assertEqual((created.assignee_name, created.created_by_name), ("Козлов Д.", "Козлов Д."))
        self.assertEqual([i.software for i in created.items], ["1С 8.3.27 клиент", "Сервер 1С"])
        self.assertEqual(created.items[0].task.host_states, {"success": 1, "waiting": 1})
        self.assertIsNone(created.items[1].task)
        self.assertEqual(len(list_rollouts(self.db, self.viewer)), 1)

    def test_update_keeps_items_unless_given_and_replaces_them_when_given(self):
        created = self.create()
        updated = update_rollout(created.id, RolloutRequestUpdate(status=RolloutStatus.blocked), None, self.db, self.operator)
        self.assertEqual((updated.status, len(updated.items)), (RolloutStatus.blocked, 2))

        updated = update_rollout(created.id, RolloutRequestUpdate(items=[RolloutItemIn(software="Git 2.55", status=RolloutItemStatus.done)]), None, self.db, self.operator)
        self.assertEqual([(i.software, i.status) for i in updated.items], [("Git 2.55", RolloutItemStatus.done)])
        self.assertEqual(self.db.query(RolloutItem).count(), 1)

    def test_update_rejects_empty_course_and_unknown_task(self):
        created = self.create()
        with self.assertRaises(HTTPException):
            update_rollout(created.id, RolloutRequestUpdate(course=None), None, self.db, self.operator)
        with self.assertRaises(HTTPException):
            update_rollout(created.id, RolloutRequestUpdate(items=[RolloutItemIn(software="X", task_run_id=uuid.uuid4())]), None, self.db, self.operator)

    def test_deleted_task_unlinks_item(self):
        created = self.create()
        self.db.delete(self.task)
        self.db.commit()
        self.db.expire_all()
        item = self.db.query(RolloutItem).filter(RolloutItem.software == "1С 8.3.27 клиент").one()
        item.task_run_id = None  # SQLite без PRAGMA foreign_keys не обнуляет ссылку сам, как Postgres (ON DELETE SET NULL)
        self.db.commit()
        self.assertIsNone(list_rollouts(self.db, self.viewer)[0].items[0].task)

    def test_delete_removes_items(self):
        created = self.create()
        delete_rollout(created.id, None, self.db, self.operator)
        self.assertEqual((self.db.query(RolloutRequest).count(), self.db.query(RolloutItem).count()), (0, 0))

    def test_assignees_are_active_editors(self):
        self.assertEqual([a.name for a in list_assignees(self.db, self.viewer)], ["Козлов Д."])


if __name__ == "__main__":
    unittest.main()
