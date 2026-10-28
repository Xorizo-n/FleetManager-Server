import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from schemas.agent import AgentHeartbeatRequest, AgentPowerReport
from services.power_state import store_power_report, updates_installing

NOW = datetime(2026, 10, 29, 10, 0, tzinfo=timezone.utc)


class PowerStateTests(unittest.TestCase):
    def test_report_is_stored_with_its_time(self):
        host = SimpleNamespace(power_state=None)
        report = AgentPowerReport(booted_at="2026-10-29T08:31:00+05:00", previous_shutdown="power_loss",
                                  previous_shutdown_at="2026-10-28T21:28:56+05:00")
        store_power_report(host, report, NOW)
        self.assertEqual(host.power_state["previous_shutdown"], "power_loss")
        self.assertEqual(host.power_state["reported_at"], NOW.isoformat())

    def test_old_agent_keeps_the_previous_report(self):
        host = SimpleNamespace(power_state={"previous_shutdown": "clean"})
        store_power_report(host, None, NOW)
        self.assertEqual(host.power_state, {"previous_shutdown": "clean"})

    def test_unknown_shutdown_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            AgentPowerReport(previous_shutdown="exploded")

    def test_updates_hold_tasks_only_while_the_report_is_fresh(self):
        fresh = {"updates_installing": True, "reported_at": (NOW - timedelta(minutes=5)).isoformat()}
        stale = {"updates_installing": True, "reported_at": (NOW - timedelta(hours=2)).isoformat()}
        self.assertTrue(updates_installing(fresh, NOW))
        self.assertFalse(updates_installing(stale, NOW))
        self.assertFalse(updates_installing({"updates_installing": False, "reported_at": NOW.isoformat()}, NOW))
        self.assertFalse(updates_installing(None, NOW))

    def test_heartbeat_accepts_the_power_field(self):
        payload = AgentHeartbeatRequest(machine_id="00000000-0000-0000-0000-000000000001", os="windows_11",
                                        power={"booted_at": None, "updates_installing": True})
        self.assertTrue(payload.power.updates_installing)


if __name__ == "__main__":
    unittest.main()
