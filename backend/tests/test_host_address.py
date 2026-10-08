import unittest

from services.host_target import resolve_host_target


class HostAddressTests(unittest.TestCase):
    def test_ip_has_priority_over_hostname(self):
        # Production fix: the server's resolver has no records for some segments,
        # and agents keep the IP fresh through the heartbeat.
        self.assertEqual(resolve_host_target("pc-01.example.local", "10.40.1.20"), "10.40.1.20")

    def test_ip_is_used_when_hostname_is_empty(self):
        self.assertEqual(resolve_host_target("  ", "10.40.1.20"), "10.40.1.20")

    def test_hostname_is_fallback_when_ip_is_empty(self):
        self.assertEqual(resolve_host_target("pc-01.example.local", None), "pc-01.example.local")

if __name__ == "__main__":
    unittest.main()
