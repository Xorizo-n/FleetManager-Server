"""Software rollout tracker: requests with programs, per-PC progress over several runs, statuses kept automatically."""

import unittest
import uuid

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.host import Host, HostGroup, HostOS
from models.rollout import RolloutItem, RolloutItemStatus, RolloutRequest, RolloutStatus
from models.task import TaskRun, TaskStatus, TaskType
from models.user import User, UserRole
from routers.rollouts import create_rollout, delete_rollout, item_progress, list_assignees, list_rollouts, update_rollout
from schemas.rollout import RolloutItemIn, RolloutRequestCreate, RolloutRequestUpdate


def run(states, status=TaskStatus.waiting, **values):
    return TaskRun(id=uuid.uuid4(), task_type=TaskType.playbook, status=status, host_ids=list(states), host_states=dict(states),
                   playbook_name="playbooks/install/install_1c_platform.yml", **values)


class ProgressTests(unittest.TestCase):
    def test_best_state_across_runs_wins(self):
        pilot = run({"a": "failed", "b": "cancelled"}, TaskStatus.failed)
        rollout = run({"a": "success", "b": "waiting", "c": "failed"})
        p = item_progress(None, [pilot, rollout])
        self.assertEqual((p.total, p.done, p.active, p.failed, p.not_started), (3, 1, 1, 1, 0))

    def test_room_hosts_without_runs_are_not_started(self):
        p = item_progress(["a", "b", "x", "y"], [run({"a": "success", "b": "ready", "z": "success"})])
        self.assertEqual((p.total, p.done, p.active, p.not_started), (4, 1, 1, 2))

    def test_old_task_without_host_states_uses_task_status(self):
        old = TaskRun(task_type=TaskType.playbook, status=TaskStatus.success, host_ids=["a", "b"])
        self.assertEqual(item_progress(None, [old]).done, 2)

    def test_nothing_to_count(self):
        self.assertIsNone(item_progress(None, []))

    def test_blank_text_becomes_none_and_course_is_required(self):
        item = RolloutItemIn(software=" Git 2.55 ", rooms="  ", note="")
        self.assertEqual((item.software, item.rooms, item.note), ("Git 2.55", None, None))
        with self.assertRaises(ValidationError):
            RolloutRequestCreate(course="   ")


class RolloutDbTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.operator = self.user("d.d.kozlov", UserRole.operator, display_name="Козлов Д.")
        self.viewer = self.user("viewer", UserRole.viewer)
        self.user("old.admin", UserRole.admin, is_active=False)
        self.room = HostGroup(id=uuid.uuid4(), name="SU5-K103")
        self.db.add(self.room)
        self.db.flush()
        self.hosts = [self.host(f"SU5-K103-W0{n}") for n in range(1, 4)]
        self.task = run({str(self.hosts[0].id): "success", str(self.hosts[1].id): "waiting"})
        self.db.add(self.task)
        self.db.commit()

    def user(self, name, role, **values):
        user = User(id=uuid.uuid4(), username=name, email=f"{name}@example.org", password_hash="x", role=role, **values)
        self.db.add(user)
        self.db.flush()
        return user

    def host(self, name):
        host = Host(id=uuid.uuid4(), hostname=name, ip_address="10.152.3.10", os=HostOS.windows_11, ssh_port=22, group_id=self.room.id)
        self.db.add(host)
        self.db.flush()
        return host

    def create(self, **values):
        return create_rollout(
            RolloutRequestCreate(
                partner="1С", course="Разработка на бизнес-ориентированных языках", rooms="K-103", schedule="Вторник 3 пара",
                assignee_id=self.operator.id,
                items=[
                    RolloutItemIn(software="1С 8.3.27 клиент", host_group_ids=[self.room.id], task_run_ids=[self.task.id]),
                    RolloutItemIn(software="Сервер 1С", rooms="K-103-OP", status=RolloutItemStatus.blocked, note="нет 64-битного дистрибутива"),
                ],
                **values,
            ),
            None, self.db, self.operator,
        )

    def test_create_counts_room_pcs_and_starts_work(self):
        created = self.create()
        client = created.items[0]
        self.assertEqual((client.progress.total, client.progress.done, client.progress.active, client.progress.not_started), (3, 1, 1, 1))
        self.assertEqual([r.id for r in client.runs], [self.task.id])
        self.assertEqual(client.status, RolloutItemStatus.in_progress)  # был «не начато»: запуск уже идёт
        self.assertIsNone(created.items[1].progress)
        self.assertEqual(created.status, RolloutStatus.in_progress)
        self.assertEqual(created.progress.total, 3)
        self.assertEqual((created.assignee_name, created.created_by_name), ("Козлов Д.", "Козлов Д."))

    def test_done_on_every_pc_marks_program_and_request_done(self):
        created = self.create()
        finish = run({str(h.id): "success" for h in self.hosts}, TaskStatus.success)
        self.db.add(finish)
        self.db.commit()
        items = [RolloutItemIn(software="1С 8.3.27 клиент", host_group_ids=[self.room.id], task_run_ids=[self.task.id, finish.id])]
        updated = update_rollout(created.id, RolloutRequestUpdate(items=items), None, self.db, self.operator)
        self.assertEqual((updated.items[0].status, updated.status), (RolloutItemStatus.done, RolloutStatus.done))

        self.host("SU5-K103-W04")  # в аудитории появился новый ПК — программа снова «в работе»
        self.db.commit()
        listed = list_rollouts(self.db, self.viewer)[0]
        self.assertEqual((listed.items[0].status, listed.status), (RolloutItemStatus.in_progress, RolloutStatus.in_progress))

    def test_blocked_request_and_items_are_not_changed_automatically(self):
        created = self.create(status=RolloutStatus.blocked)
        self.assertEqual((created.status, created.items[1].status), (RolloutStatus.blocked, RolloutItemStatus.blocked))

    def test_update_keeps_items_unless_given(self):
        created = self.create()
        updated = update_rollout(created.id, RolloutRequestUpdate(notes="ждём дистрибутив"), None, self.db, self.operator)
        self.assertEqual((updated.notes, len(updated.items)), ("ждём дистрибутив", 2))

    def test_update_rejects_empty_course_and_unknown_refs(self):
        created = self.create()
        for payload in (
            RolloutRequestUpdate(course=None),
            RolloutRequestUpdate(items=[RolloutItemIn(software="X", task_run_ids=[uuid.uuid4()])]),
            RolloutRequestUpdate(items=[RolloutItemIn(software="X", host_group_ids=[uuid.uuid4()])]),
        ):
            with self.assertRaises(HTTPException):
                update_rollout(created.id, payload, None, self.db, self.operator)

    def test_deleted_run_is_skipped(self):
        created = self.create()
        self.db.delete(self.task)
        self.db.commit()
        item = list_rollouts(self.db, self.viewer)[0].items[0]
        self.assertEqual((item.runs, item.progress.not_started), ([], 3))

    def test_delete_removes_items(self):
        created = self.create()
        delete_rollout(created.id, None, self.db, self.operator)
        self.assertEqual((self.db.query(RolloutRequest).count(), self.db.query(RolloutItem).count()), (0, 0))

    def test_assignees_are_active_editors(self):
        self.assertEqual([a.name for a in list_assignees(self.db, self.viewer)], ["Козлов Д."])


if __name__ == "__main__":
    unittest.main()
