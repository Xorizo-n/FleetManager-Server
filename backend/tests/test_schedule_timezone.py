import unittest
from datetime import datetime, timezone

from services.ansible_runner import schedule_is_due


class ScheduleTimezoneTests(unittest.TestCase):
    """Cron в расписаниях — местное время (Екатеринбург, UTC+5), а не UTC."""

    def test_nine_oclock_is_nine_in_yekaterinburg(self):
        # 09:00:30 по Екатеринбургу = 04:00:30 UTC
        self.assertTrue(schedule_is_due("0 9 * * *", datetime(2026, 10, 12, 4, 0, 30, tzinfo=timezone.utc)))

    def test_nine_utc_is_not_nine_local(self):
        self.assertFalse(schedule_is_due("0 9 * * *", datetime(2026, 10, 12, 9, 0, 30, tzinfo=timezone.utc)))

    def test_only_within_the_last_minute(self):
        self.assertFalse(schedule_is_due("0 9 * * *", datetime(2026, 10, 12, 4, 2, 0, tzinfo=timezone.utc)))

    def test_every_five_minutes(self):
        self.assertTrue(schedule_is_due("*/5 * * * *", datetime(2026, 10, 12, 4, 10, 15, tzinfo=timezone.utc)))
        self.assertFalse(schedule_is_due("*/5 * * * *", datetime(2026, 10, 12, 4, 12, 15, tzinfo=timezone.utc)))


if __name__ == "__main__":
    unittest.main()
