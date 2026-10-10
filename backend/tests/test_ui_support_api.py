"""API the redesigned UI relies on: group targets, schedules, task authors, weekly stats."""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from pydantic import ValidationError

from main import app
from models.playbook import PlaybookSchedule
from models.task import TaskRun, TaskStatus, TaskType
from schemas.playbook import PlaybookRunRequest, PlaybookScheduleCreate, PlaybookScheduleUpdate
from services.inventory_generator import group_with_descendants, resolve_target_host_ids
from services.schedule_targets import next_run_at, schedule_group_ids, schedule_out


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return self


class _QueuedDb:
    """Returns prepared results for consecutive execute() calls."""

    def __init__(self, *results):
        self._results = list(results)
        self.calls = 0

    def execute(self, _query):
        self.calls += 1
        return _Result(self._results.pop(0))


BUILDING, FLOOR, ROOM, OTHER = (uuid.uuid4() for _ in range(4))
GROUP_ROWS = [(BUILDING, None), (FLOOR, BUILDING), (ROOM, FLOOR), (OTHER, None)]


class GroupTargetTests(unittest.TestCase):
    def test_building_includes_floors_and_rooms(self):
        self.assertEqual(group_with_descendants(_QueuedDb(GROUP_ROWS), [BUILDING]), {BUILDING, FLOOR, ROOM})

    def test_room_is_only_itself(self):
        self.assertEqual(group_with_descendants(_QueuedDb(GROUP_ROWS), [ROOM]), {ROOM})

    def test_no_groups_skips_the_query(self):
        db = _QueuedDb()
        self.assertEqual(group_with_descendants(db, []), set())
        self.assertEqual(db.calls, 0)

    def test_cycle_in_data_terminates(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        self.assertEqual(group_with_descendants(_QueuedDb([(a, b), (b, a)]), [a]), {a, b})

    def test_targets_merge_hosts_and_groups_without_duplicates(self):
        explicit, in_room = uuid.uuid4(), uuid.uuid4()
        db = _QueuedDb(GROUP_ROWS, [in_room, explicit])
        self.assertEqual(resolve_target_host_ids(db, [explicit], [BUILDING]), [str(explicit), str(in_room)])

    def test_run_request_accepts_several_groups(self):
        payload = PlaybookRunRequest(repo_id=uuid.uuid4(), playbook_name="site.yml", host_group_ids=[BUILDING, ROOM])
        self.assertEqual(payload.host_group_ids, [BUILDING, ROOM])
        self.assertIsNone(payload.host_group_id)


class ScheduleTests(unittest.TestCase):
    def _schedule(self, **overrides):
        values = dict(
            id=uuid.uuid4(),
            repo_id=uuid.uuid4(),
            playbook_name="playbooks/install/install_7zip.yml",
            host_group_id=None,
            host_group_ids=None,
            host_ids=None,
            extra_vars=None,
            cron_expression="0 3 * * *",
            enabled=True,
            created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        values.update(overrides)
        return PlaybookSchedule(**values)

    def test_invalid_cron_is_rejected(self):
        with self.assertRaises(ValidationError):
            PlaybookScheduleCreate(repo_id=uuid.uuid4(), playbook_name="x.yml", cron_expression="every night")

    def test_cron_whitespace_is_normalized(self):
        payload = PlaybookScheduleCreate(repo_id=uuid.uuid4(), playbook_name="x.yml", cron_expression=" 0  3 * * * ")
        self.assertEqual(payload.cron_expression, "0 3 * * *")

    def test_update_allows_partial_payload(self):
        payload = PlaybookScheduleUpdate(enabled=False)
        self.assertEqual(payload.model_dump(exclude_unset=True), {"enabled": False})

    def test_legacy_single_group_is_kept(self):
        legacy = uuid.uuid4()
        schedule = self._schedule(host_group_id=legacy, host_group_ids=[str(BUILDING), str(legacy)])
        self.assertEqual(schedule_group_ids(schedule), [str(BUILDING), str(legacy)])

    def test_next_run(self):
        now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(next_run_at("0 3 * * *", now), datetime(2026, 10, 11, 3, 0, tzinfo=timezone.utc))

    def test_out_has_targets_and_next_run_only_when_enabled(self):
        now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
        host = uuid.uuid4()
        out = schedule_out(self._schedule(host_group_ids=[str(ROOM)], host_ids=[str(host)]), now)
        self.assertEqual(out.host_group_ids, [str(ROOM)])
        self.assertEqual(out.host_ids, [host])
        self.assertEqual(out.extra_vars, {})
        self.assertIsNotNone(out.next_run_at)
        self.assertIsNone(schedule_out(self._schedule(enabled=False), now).next_run_at)


class TaskAuthorTests(unittest.TestCase):
    def test_author_names_are_resolved_in_one_query(self):
        from routers.tasks import with_author_names

        author = uuid.uuid4()

        def task(created_by):
            return TaskRun(
                id=uuid.uuid4(),
                task_type=TaskType.playbook,
                playbook_name="site.yml",
                host_ids=[],
                status=TaskStatus.success,
                created_by=created_by,
                created_at=datetime.now(timezone.utc),
            )

        db = _QueuedDb([(author, "operator1")])
        result = with_author_names(db, [task(author), task(None)])
        self.assertEqual([item.created_by_name for item in result], ["operator1", None])
        self.assertEqual(db.calls, 1)


class WeeklyStatsTests(unittest.TestCase):
    def test_all_seven_days_are_returned(self):
        from routers.dashboard import weekly_run_stats

        now = datetime.now(timezone.utc)
        db = _QueuedDb([(now, TaskStatus.success), (now, TaskStatus.failed), (now, TaskStatus.running)])
        stats = weekly_run_stats(db=db, _=SimpleNamespace())
        self.assertEqual(len(stats), 7)
        self.assertEqual((stats[-1].success, stats[-1].failed), (1, 1))
        self.assertTrue(all(item.success == 0 and item.failed == 0 for item in stats[:-1]))


class AlertSummaryTests(unittest.TestCase):
    def test_counts_come_from_the_database_not_a_page_of_alerts(self):
        from routers.agent import alerts_summary

        class _Db:
            def execute(self, _query):
                return SimpleNamespace(one=lambda: (788, 13))

        summary = alerts_summary(days=7, db=_Db(), _=SimpleNamespace())
        self.assertEqual((summary.days, summary.total, summary.hosts), (7, 788, 13))


class RouteTests(unittest.TestCase):
    def test_new_routes_are_registered(self):
        routes = {(route.path, method) for route in app.routes for method in getattr(route, "methods", ())}
        for expected in [
            ("/playbooks/schedules/{schedule_id}", "PATCH"),
            ("/hosts/groups/{group_id}", "PATCH"),
            ("/hosts/groups/{group_id}", "DELETE"),
            ("/hosts/delete", "POST"),
            ("/software/packages", "GET"),
            ("/software/package-hosts", "GET"),
            ("/agent/alerts", "GET"),
            ("/agent/alerts/summary", "GET"),
        ]:
            self.assertIn(expected, routes)


if __name__ == "__main__":
    unittest.main()
