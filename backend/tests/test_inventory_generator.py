import unittest
import uuid

from models.host import Host, HostOS
from services.inventory_generator import build_inventory_dict


class _ScalarResult:
    def __init__(self, hosts):
        self._hosts = hosts

    def scalars(self):
        return self

    def all(self):
        return self._hosts


class _FakeDb:
    def __init__(self, hosts):
        self.hosts = hosts

    def execute(self, _query):
        return _ScalarResult(self.hosts)


class InventoryGeneratorTests(unittest.TestCase):
    def test_inventory_includes_host_ssh_port(self):
        host = Host(
            id=uuid.uuid4(),
            hostname="pc-01",
            ip_address="10.40.1.20",
            os=HostOS.windows_11,
            ssh_port=5022,
        )
        inventory = build_inventory_dict(_FakeDb([host]))
        hosts = inventory["all"]["children"]["ungrouped"]["hosts"]
        self.assertIn(str(host.id), hosts)
        self.assertNotIn("pc-01", hosts)
        host_vars = hosts[str(host.id)]
        self.assertEqual(host_vars["ansible_port"], 5022)
        self.assertEqual(host_vars["ansible_shell_type"], "powershell")
        self.assertIn(str(host.id), inventory["all"]["children"]["Win_Hosts"]["hosts"])
        self.assertIn(str(host.id), inventory["all"]["children"]["windows"]["hosts"])


if __name__ == "__main__":
    unittest.main()
