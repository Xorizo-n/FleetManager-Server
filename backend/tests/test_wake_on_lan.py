import ipaddress
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from models.host import Host, HostGroup, HostOS, HostStatus
from services.wake_on_lan import magic_packet_script, normalize_mac, primary_adapter, relay_candidates, wake_target

WIRED = {"name": "Ethernet", "mac_address": "34-5A-60-BF-91-C7", "ipv4": ["10.152.5.56/25"], "status": "Up", "media_type": "802.3"}
WIFI = {"name": "Wi-Fi", "mac_address": "aa:bb:cc:dd:ee:ff", "ipv4": ["192.168.1.5/24"], "status": "Up", "media_type": "Native 802.11"}


def _host(ip, status=HostStatus.offline, adapters=None, mac=None, seen_minutes_ago=None):
    host = Host(id=uuid.uuid4(), hostname=f"PC-{ip}", ip_address=ip, os=HostOS.windows_11, ssh_port=22, status=status)
    host.hw_network_adapters = adapters
    host.hw_mac_address = mac
    host.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=seen_minutes_ago) if seen_minutes_ago is not None else None
    return host


class _Query:
    def __init__(self, hosts):
        self.hosts = hosts

    def filter(self, *_):
        return self

    def all(self):
        return [h for h in self.hosts if h.status == HostStatus.online and h.ip_address]


class MacTests(unittest.TestCase):
    def test_normalized_like_windows(self):
        for raw in ("34:5a:60:bf:91:c7", "34-5A-60-BF-91-C7", "345A60BF91C7", " 34.5a.60.bf.91.c7 "):
            self.assertEqual(normalize_mac(raw), "34-5A-60-BF-91-C7", raw)

    def test_garbage_and_placeholders_are_rejected(self):
        for raw in (None, "", "34-5A-60", "00-00-00-00-00-00", "FF-FF-FF-FF-FF-FF", "zz-zz-zz-zz-zz-zz"):
            self.assertIsNone(normalize_mac(raw), raw)


class PrimaryAdapterTests(unittest.TestCase):
    def test_adapter_with_the_host_ip_wins(self):
        self.assertIs(primary_adapter([WIFI, WIRED], "10.152.5.56"), WIRED)

    def test_wired_up_adapter_when_ip_unknown(self):
        self.assertIs(primary_adapter([WIFI, WIRED], None), WIRED)

    def test_no_usable_adapter(self):
        self.assertIsNone(primary_adapter([{"mac_address": ""}], "10.0.0.1"))
        self.assertIsNone(primary_adapter(None, "10.0.0.1"))


class WakeTargetTests(unittest.TestCase):
    def test_mac_and_exact_subnet_from_the_agent(self):
        mac, network, exact = wake_target(_host("10.152.5.56", adapters=[WIRED]))
        self.assertEqual((mac, str(network), exact), ("34-5A-60-BF-91-C7", "10.152.5.0/25", True))

    def test_without_prefix_the_subnet_is_guessed_as_24(self):
        mac, network, exact = wake_target(_host("10.152.5.56", mac="34-5A-60-BF-91-C7"))
        self.assertEqual((mac, str(network), exact), ("34-5A-60-BF-91-C7", "10.152.5.0/24", False))

    def test_old_agent_has_no_mac(self):
        self.assertIsNone(wake_target(_host("10.152.5.56"))[0])


class RelayTests(unittest.TestCase):
    def test_online_neighbours_of_the_subnet_most_recent_first(self):
        target = _host("10.152.5.56")
        old = _host("10.152.5.66", HostStatus.online, seen_minutes_ago=4)
        fresh = _host("10.152.5.67", HostStatus.online, seen_minutes_ago=1)
        other_half = _host("10.152.5.200", HostStatus.online, seen_minutes_ago=0)  # /25: другая половина
        offline = _host("10.152.5.70")
        db = SimpleNamespace(query=lambda _model: _Query([target, old, fresh, other_half, offline]))
        relays = relay_candidates(db, ipaddress.IPv4Network("10.152.5.0/25"), {str(target.id)})
        self.assertEqual(relays, [fresh, old])


class MagicPacketScriptTests(unittest.TestCase):
    def test_packet_goes_to_both_broadcasts_for_every_mac(self):
        script = magic_packet_script(["34-5A-60-BF-91-C7", "34-5A-60-BF-91-C8"], ipaddress.IPv4Network("10.152.5.0/25"))
        self.assertIn("'34-5A-60-BF-91-C7','34-5A-60-BF-91-C8'", script)
        self.assertIn("'255.255.255.255', '10.152.5.127'", script)
        self.assertIn("fleet-wol-sent=", script)


class ExportAndInventoryTests(unittest.TestCase):
    def test_hosts_csv_has_mac_and_excel_friendly_format(self):
        from routers.hosts import export_hosts_csv

        building = HostGroup(id=uuid.uuid4(), name="SU5")
        room = HostGroup(id=uuid.uuid4(), name="SU5-K204", parent=building)
        host = _host("10.152.5.56", adapters=[WIRED], mac="34-5A-60-BF-91-C7")
        host.hostname, host.group, host.hw_total_memory_bytes = "SU5-K204-W26", room, 16 * 1024 ** 3
        db = SimpleNamespace(execute=lambda _q: SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [host])))

        body = export_hosts_csv(db=db, _=None).body.decode("utf-8")

        self.assertTrue(body.startswith("﻿Имя;IP;MAC;Группа"))
        self.assertIn("SU5-K204-W26;10.152.5.56;34-5A-60-BF-91-C7;SU5 › SU5-K204;offline;", body)
        self.assertIn(";16;", body)

    def test_inventory_carries_the_mac(self):
        from services.inventory_generator import build_inventory_dict, build_inventory_ini

        host = _host("10.152.5.56", mac="34-5A-60-BF-91-C7")
        host.group = None
        host.group_id = None
        db = SimpleNamespace(execute=lambda _q: SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [host])))
        self.assertEqual(build_inventory_dict(db)["all"]["children"]["ungrouped"]["hosts"][str(host.id)]["mac_address"], "34-5A-60-BF-91-C7")
        self.assertIn("mac_address=34-5A-60-BF-91-C7", build_inventory_ini(db))


if __name__ == "__main__":
    unittest.main()
