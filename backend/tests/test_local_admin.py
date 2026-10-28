import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from config import settings
from services import local_admin
from services.ssh_health import ssh_blocked_reason, ssh_problems


def state(**kw):
    return {"reported_at": datetime.now(timezone.utc).isoformat(), **kw}


class PreferredTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.multiple(settings, local_admin_fallback=True, local_admin_login="admin")
        p.start()
        self.addCleanup(p.stop)

    def preferred(self, ssh_state, login="at\\Sergey.Mirzagitov"):
        return local_admin.preferred(SimpleNamespace(ssh_state=ssh_state), login)

    def test_broken_trust_or_unreachable_controller_goes_local(self):
        self.assertEqual(self.preferred(state(domain_trust="broken", local_admin="ok")), "admin")
        self.assertEqual(self.preferred(state(domain_trust="unreachable")), "admin")  # старый агент не знает local_admin

    def test_healthy_domain_keeps_the_domain_login(self):
        self.assertIsNone(self.preferred(state(domain_trust="ok", local_admin="ok")))
        self.assertIsNone(self.preferred(None))

    def test_stale_report_is_not_trusted(self):
        old = state(domain_trust="broken")
        old["reported_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.assertIsNone(self.preferred(old))

    def test_nothing_to_fall_back_to(self):
        self.assertIsNone(self.preferred(state(domain_trust="broken", local_admin="disabled")))
        self.assertIsNone(self.preferred(state(domain_trust="broken"), login="admin"))  # уже локальная
        with mock.patch.multiple(settings, local_admin_fallback=False):
            self.assertIsNone(self.preferred(state(domain_trust="broken")))


class HostCardTests(unittest.TestCase):
    def test_broken_trust_with_local_admin_does_not_block(self):
        s = state(domain_trust="broken", local_admin="ok")
        self.assertIsNone(ssh_blocked_reason(s))
        self.assertIn("сервер входит под локальным администратором", " ".join(ssh_problems(s)))

    def test_broken_trust_without_local_admin_blocks(self):
        self.assertIn("доверие", ssh_blocked_reason(state(domain_trust="broken", local_admin="missing")))
        self.assertIn("локальная учётка для запасного входа: нет", " ".join(ssh_problems(state(local_admin="missing"))))


if __name__ == "__main__":
    unittest.main()
