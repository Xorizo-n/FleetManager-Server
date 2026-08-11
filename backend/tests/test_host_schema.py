import unittest

from pydantic import ValidationError

from schemas.host import HostCreate


class HostSchemaTests(unittest.TestCase):
    def test_hostname_only_is_valid(self):
        host = HostCreate(hostname="pc-01.example.local", os="windows_11")
        self.assertEqual(host.hostname, "pc-01.example.local")
        self.assertIsNone(host.ip_address)

    def test_ip_only_is_valid(self):
        host = HostCreate(ip_address="10.40.1.20", os="windows_11")
        self.assertEqual(host.ip_address, "10.40.1.20")
        self.assertIsNone(host.hostname)

    def test_both_addresses_empty_are_rejected(self):
        with self.assertRaises(ValidationError):
            HostCreate(hostname="  ", ip_address="", os="windows_11")


if __name__ == "__main__":
    unittest.main()
