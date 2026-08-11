import unittest

from services.host_diagnostic_utils import format_stage, inventory_host_key, sanitize_detail


class HostDiagnosticUtilityTests(unittest.TestCase):
    def test_format_stage_marks_success(self):
        self.assertEqual(format_stage("TCP", "port 22 is open", ok=True), "[OK] TCP: port 22 is open")

    def test_inventory_key_is_uuid_string(self):
        self.assertEqual(inventory_host_key("3c6d"), "3c6d")

    def test_sanitize_detail_removes_secret_values(self):
        self.assertNotIn("super-secret", sanitize_detail("authentication failed: super-secret", ["super-secret"]))

    def test_tcp_stage_uses_the_configured_port(self):
        from services.host_diagnostics import _ssh_port

        self.assertEqual(_ssh_port(type("Host", (), {"ssh_port": 5022})()), 5022)


if __name__ == "__main__":
    unittest.main()
