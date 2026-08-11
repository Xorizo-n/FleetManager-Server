import unittest

from services.host_target import resolve_host_target


class HostAddressTests(unittest.TestCase):
    def test_hostname_has_priority_over_ip(self):
        self.assertEqual(resolve_host_target("pc-01.example.local", "10.40.1.20"), "pc-01.example.local")

    def test_ip_is_fallback_when_hostname_is_empty(self):
        self.assertEqual(resolve_host_target("  ", "10.40.1.20"), "10.40.1.20")

if __name__ == "__main__":
    unittest.main()
