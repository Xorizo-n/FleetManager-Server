import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from services import host_dedup
from services.host_dedup import _replace_id, adoptable_host, is_stale, reset_for_new_install, same_machine

NOW = datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc)


def host(name="SU5-E302-OP", seen_minutes_ago=0, mac=None, serial=None, ip="10.152.16.111", adapters=None):
    return SimpleNamespace(
        id=uuid.uuid4(), hostname=name, last_seen_at=NOW - timedelta(minutes=seen_minutes_ago), created_at=NOW - timedelta(days=3),
        hw_mac_address=mac, hw_network_adapters=adapters, hw_serial_number=serial, ip_address=ip,
    )


class SameMachineTests(unittest.TestCase):
    def test_script_agent_record_matches_by_address(self):
        # Скриптовый агент не присылал MAC, а серийным номером записывал модель диска
        old = host(serial="AirDisk 512GB SSD (477 GB)")
        new = host(serial="S07SDCS5007HA065043", mac="00-E0-4C-7A-90-A4")
        self.assertTrue(same_machine(old, new))

    def test_mac_or_serial_match_even_after_the_address_changed(self):
        self.assertTrue(same_machine(host(mac="34-5A-60-BF-96-1E", ip="10.152.1.64"), host(mac="34:5a:60:bf:96:1e", ip="10.152.1.179")))
        self.assertTrue(same_machine(host(serial="S07GDCS7001HA0650426", ip="10.152.1.64"), host(serial="S07GDCS7001HA0650426", ip="10.152.1.179")))
        self.assertTrue(same_machine(host(adapters=[{"mac_address": "AA-BB-CC-DD-EE-01"}], ip="1.1.1.1"), host(mac="AA-BB-CC-DD-EE-01", ip="2.2.2.2")))

    def test_different_pc_with_the_same_name_is_not_merged(self):
        # SU5-K118-W09: два физических ПК под одним именем — разные MAC, серийники и адреса
        old = host(name="SU5-K118-W09", serial="S07GDCS7001HA0650668", mac="34-5A-60-BF-92-D2", ip="10.152.1.73")
        new = host(name="SU5-K118-W09", serial="S07GDCS7001HA0650666", mac="34-5A-60-BF-93-5F", ip="10.152.1.181")
        self.assertFalse(same_machine(old, new))

    def test_placeholder_serials_prove_nothing(self):
        self.assertFalse(same_machine(host(serial="System Serial Number", ip="1.1.1.1"), host(serial="System Serial Number", ip="2.2.2.2")))

    def test_another_name_is_another_host(self):
        # SU5-J207-OP -> SU5-J107-OP на том же адресе: ошибка в имени, сливать нельзя
        self.assertFalse(same_machine(host(name="SU5-J207-OP"), host(name="SU5-J107-OP")))

    def test_domain_suffix_and_case_do_not_matter(self):
        self.assertTrue(same_machine(host(name="su5-e302-op.at.urfu.ru"), host(name="SU5-E302-OP")))


class AdoptionTests(unittest.TestCase):
    def adopt(self, namesakes):
        with mock.patch.object(host_dedup, "_namesakes", return_value=namesakes):
            return adoptable_host(mock.Mock(), "SU5-E302-OP", NOW)

    def test_stale_record_of_the_name_is_adopted(self):
        old = host(seen_minutes_ago=24 * 60)
        self.assertIs(self.adopt([old]), old)

    def test_name_held_by_a_reporting_pc_is_not_taken(self):
        self.assertIsNone(self.adopt([host(seen_minutes_ago=24 * 60), host(seen_minutes_ago=3)]))

    def test_most_recently_seen_stale_record_wins(self):
        older, newer = host(seen_minutes_ago=3 * 24 * 60), host(seen_minutes_ago=60)
        self.assertIs(self.adopt([older, newer]), newer)

    def test_no_name_no_adoption(self):
        self.assertIsNone(adoptable_host(mock.Mock(), None, NOW))

    def test_stale_window_matches_the_clone_guard(self):
        self.assertFalse(is_stale(host(seen_minutes_ago=5), NOW))
        self.assertTrue(is_stale(host(seen_minutes_ago=16), NOW))

    def test_new_install_drops_pinned_host_keys_and_pending_update(self):
        record = SimpleNamespace(ssh_state={"host_keys": ["ssh-ed25519 AAAA"]}, agent_update_target="2026.10.25.25")
        reset_for_new_install(record)
        self.assertIsNone(record.ssh_state)
        self.assertIsNone(record.agent_update_target)


class ReplaceIdTests(unittest.TestCase):
    def test_lists_dicts_and_nesting(self):
        old, new = "a", "b"
        self.assertEqual(_replace_id(["a", "c"], old, new), ["b", "c"])
        self.assertEqual(_replace_id(["a", "b"], old, new), ["b"])
        self.assertEqual(_replace_id({"a": "success", "c": "failed"}, old, new), {"b": "success", "c": "failed"})
        self.assertEqual(_replace_id({"as_user": ["a"], "fallback": {"a": "нет логина"}}, old, new), {"as_user": ["b"], "fallback": {"b": "нет логина"}})
        self.assertIsNone(_replace_id(None, old, new))


if __name__ == "__main__":
    unittest.main()
