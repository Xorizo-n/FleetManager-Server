import unittest

from services.host_target import resolve_host_target
from services.wake_on_lan import agent_lan_address

WIRED = {"name": "Ethernet", "mac_address": "34-5A-60-BF-91-C7", "ipv4": ["10.152.5.66/25"], "status": "Up", "media_type": "802.3"}
WIFI = {"name": "Wi-Fi", "mac_address": "B0-47-E9-C1-D9-7D", "ipv4": ["10.152.200.7/24"], "status": "Up", "media_type": "Native 802.11"}
WIFI_APIPA = {**WIFI, "ipv4": ["169.254.182.180/16"]}


class HostAddressTests(unittest.TestCase):
    def test_ip_has_priority_over_hostname(self):
        # Production fix: the server's resolver has no records for some segments,
        # and agents keep the IP fresh through the heartbeat.
        self.assertEqual(resolve_host_target("pc-01.example.local", "10.40.1.20"), "10.40.1.20")

    def test_ip_is_used_when_hostname_is_empty(self):
        self.assertEqual(resolve_host_target("  ", "10.40.1.20"), "10.40.1.20")

    def test_hostname_is_fallback_when_ip_is_empty(self):
        self.assertEqual(resolve_host_target("pc-01.example.local", None), "pc-01.example.local")


class AgentLanAddressTests(unittest.TestCase):
    def test_source_address_of_the_pc_itself_is_kept(self):
        self.assertEqual(agent_lan_address([WIFI, WIRED], "10.152.5.66"), "10.152.5.66")
        self.assertEqual(agent_lan_address([WIFI, WIRED], "10.152.200.7"), "10.152.200.7")

    def test_vpn_pool_address_is_replaced_by_the_wired_adapter(self):
        # Built-in Windows VPN on SU5 tunnels the heartbeat too: the server sees the VPN address.
        self.assertEqual(agent_lan_address([WIFI, WIRED], "10.200.17.4"), "10.152.5.66")

    def test_wifi_only_pc_and_apipa_is_skipped(self):
        self.assertEqual(agent_lan_address([WIFI], "10.200.17.4"), "10.152.200.7")
        self.assertEqual(agent_lan_address([WIFI_APIPA, WIRED], "10.200.17.4"), "10.152.5.66")

    def test_disconnected_adapters_and_old_agents_fall_back_to_the_source(self):
        self.assertEqual(agent_lan_address([{**WIRED, "status": "Disconnected"}], "10.200.17.4"), "10.200.17.4")
        self.assertEqual(agent_lan_address([WIFI_APIPA], "10.200.17.4"), "10.200.17.4")
        self.assertEqual(agent_lan_address([], "10.152.5.66"), "10.152.5.66")
        self.assertEqual(agent_lan_address(None, "10.152.5.66"), "10.152.5.66")


if __name__ == "__main__":
    unittest.main()
