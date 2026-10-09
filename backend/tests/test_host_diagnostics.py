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
    """The agent reports a short name; the PC may be in at.urfu.ru or in the old
    rtf.ustu zone, whose records often point at other PCs. The connection uses the
    IP the agent reports, so DNS only has to agree with it."""

    DOMAINS = ["at.urfu.ru", "rtf.ustu"]

    def _run(self, records, hostname, target):
        import socket
        from unittest import mock

        from services.host_diagnostics import _dns_stage

        def fake_getaddrinfo(name, *_args, **_kwargs):
            address = records.get(name.rstrip("."))
            if address is None:
                raise socket.gaierror(-2, "Name or service not known")
            return [(2, 1, 6, "", (address, 0))]

        with mock.patch("services.host_diagnostics.socket.getaddrinfo", side_effect=fake_getaddrinfo):
            return _dns_stage(hostname, target, self.DOMAINS)

    def test_name_in_at_urfu_ru_matches_the_agent_ip(self):
        ok, message = self._run({"SU5-D206-TEMP.at.urfu.ru": "10.152.128.88"}, "SU5-D206-TEMP", "10.152.128.88")
        self.assertTrue(ok)
        self.assertIn("SU5-D206-TEMP.at.urfu.ru -> 10.152.128.88, matches the agent IP", message)

    def test_stale_record_in_the_other_zone_is_reported(self):
        records = {"MR32-411-02.at.urfu.ru": "10.40.131.203", "MR32-411-02.rtf.ustu": "10.40.131.194"}
        ok, message = self._run(records, "MR32-411-02", "10.40.131.203")
        self.assertTrue(ok)
        self.assertIn("stale record(s): MR32-411-02.rtf.ustu -> 10.40.131.194", message)

    def test_only_a_stale_record_is_a_warning(self):
        ok, message = self._run({"MR32-411-18.rtf.ustu": "10.40.131.201"}, "MR32-411-18", "10.40.131.197")
        self.assertIsNone(ok)
        self.assertIn("stale DNS record(s): MR32-411-18.rtf.ustu -> 10.40.131.201", message)
        self.assertIn("the agent reports 10.40.131.197", message)

    def test_unresolvable_name_is_not_fatal_when_connecting_by_ip(self):
        ok, message = self._run({}, "SU5-D206-TEMP", "10.152.128.88")
        self.assertIsNone(ok)
        self.assertIn("does not resolve in at.urfu.ru, rtf.ustu; connecting by IP 10.152.128.88", message)

    def test_unresolvable_name_is_fatal_when_it_is_the_target(self):
        import socket

        with self.assertRaises(socket.gaierror):
            self._run({}, "pc-01.example.local", "pc-01.example.local")

    def test_no_hostname_is_skipped(self):
        from services.host_diagnostics import _dns_stage

        self.assertEqual(_dns_stage("  ", "10.40.1.20")[0], None)

    def test_search_domains_come_from_resolv_conf(self):
        import os
        import tempfile

        from services.host_diagnostics import _search_domains

        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False, encoding="utf-8") as handle:
            handle.write("nameserver 127.0.0.11\nsearch at.urfu.ru rtf.ustu\noptions ndots:0\n")
        try:
            self.assertEqual(_search_domains(handle.name), ["at.urfu.ru", "rtf.ustu"])
        finally:
            os.unlink(handle.name)


if __name__ == "__main__":
    unittest.main()
