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


class DnsStageTests(unittest.TestCase):
    """The diagnostic connects by the IP the agent reports; the hostname may live in a
    DNS zone the server's resolver does not search (SU5-D206-TEMP in at.urfu.ru)."""

    def test_unresolvable_name_is_not_fatal_when_connecting_by_ip(self):
        import socket
        from unittest import mock

        from services.host_diagnostics import _dns_stage

        with mock.patch("services.host_diagnostics.socket.getaddrinfo", side_effect=socket.gaierror(-3, "Temporary failure in name resolution")):
            ok, message = _dns_stage("SU5-D206-TEMP", "10.152.128.88")
        self.assertIsNone(ok)
        self.assertIn("connecting by IP 10.152.128.88", message)

    def test_unresolvable_name_is_fatal_when_it_is_the_target(self):
        import socket
        from unittest import mock

        from services.host_diagnostics import _dns_stage

        with mock.patch("services.host_diagnostics.socket.getaddrinfo", side_effect=socket.gaierror(-2, "Name or service not known")):
            with self.assertRaises(socket.gaierror):
                _dns_stage("pc-01.example.local", "pc-01.example.local")

    def test_resolved_name_is_reported(self):
        from unittest import mock

        from services.host_diagnostics import _dns_stage

        with mock.patch("services.host_diagnostics.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.40.1.20", 0))]):
            ok, message = _dns_stage("pc-01", "10.40.1.20")
        self.assertTrue(ok)
        self.assertIn("10.40.1.20", message)

    def test_no_hostname_is_skipped(self):
        from services.host_diagnostics import _dns_stage

        self.assertEqual(_dns_stage("  ", "10.40.1.20")[0], None)


if __name__ == "__main__":
    unittest.main()
