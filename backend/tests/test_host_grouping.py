import unittest
import uuid

from models.host import Host, HostGroup, HostOS
from services.host_grouping import auto_group_host, find_group_by_name, parse_host_name, should_move
from services.inventory_generator import build_inventory_dict


class _GroupResult:
    def __init__(self, groups):
        self._groups = groups

    def scalar_one_or_none(self):
        assert len(self._groups) <= 1, "names must be unique within a parent"
        return self._groups[0] if self._groups else None

    def scalars(self):
        return self

    def all(self):
        return self._groups


class _FakeGroupDb:
    """Just enough of a Session for host_grouping: evaluates name / parent_id conditions."""

    def __init__(self, groups=()):
        self.groups = list(groups)

    def execute(self, query):
        clause = query.whereclause
        conditions = list(getattr(clause, "clauses", [clause]))

        def matches(group):
            for condition in conditions:
                value = getattr(condition.right, "value", None)  # IS NULL -> None
                if getattr(group, condition.left.key) != value:
                    return False
            return True

        return _GroupResult([group for group in self.groups if matches(group)])

    def add(self, group):
        self.groups.append(group)

    def flush(self):
        for group in self.groups:
            if group.id is None:
                group.id = uuid.uuid4()
            if group.parent is not None:
                group.parent_id = group.parent.id

    def names(self):
        return sorted(group.name for group in self.groups)


def _host(name, group=None):
    host = Host(id=uuid.uuid4(), hostname=name, ip_address="10.152.128.88", os=HostOS.windows_11, ssh_port=22)
    if group is not None:
        host.group = group
        host.group_id = group.id
    return host


class _HostsDb:
    def __init__(self, hosts):
        self.hosts = hosts

    def execute(self, _query):
        return _GroupResult(self.hosts)


class HostNameTests(unittest.TestCase):
    def test_building_room_floor_from_the_name(self):
        parts = parse_host_name("SU5-D206-TEMP")
        self.assertEqual((parts.building, parts.room, parts.floor), ("SU5", "D206", "2"))
        self.assertEqual((parts.building_group, parts.floor_group, parts.room_group), ("SU5", "2 этаж", "SU5-D206"))

    def test_existing_production_names(self):
        self.assertEqual(parse_host_name("MR32-411-01").room_group, "MR32-411")
        self.assertEqual(parse_host_name("MR32-411-01").floor, "4")
        # Тип ПК может содержать дефисы; номер аудитории с нулём — этаж 0.
        self.assertEqual(parse_host_name("MR32-025-1-04").room_group, "MR32-025")
        self.assertEqual(parse_host_name("mr32-044-sergey").room_group, "MR32-044")

    def test_names_outside_the_scheme_are_ignored(self):
        for name in ("DESKTOP-ABC123", "WIN10-VDI000", "SU5-D206", "pc-01", "", None, "SU5-OFFICE-01"):
            self.assertIsNone(parse_host_name(name), name)

    def test_autodomain_dotnet_pattern_is_accepted(self):
        dotnet = r"^(?<Building>[A-Z0-9]+)-(?<Room>[A-Z]*(?<Floor>[0-9])[0-9]*[A-Z]*)-[A-Z0-9-]+$"
        self.assertEqual(parse_host_name("SU5-E302-OP", dotnet).room_group, "SU5-E302")


class MoveDecisionTests(unittest.TestCase):
    def test_ungrouped_host_is_grouped(self):
        self.assertTrue(should_move(None, False, "SU5-D206"))

    def test_manual_group_of_another_name_is_kept(self):
        self.assertFalse(should_move("Преподавательские", False, "SU5-D206"))

    def test_automatic_group_follows_the_name(self):
        self.assertTrue(should_move("SU5-D204", True, "SU5-D206"))


class AutoGroupTests(unittest.TestCase):
    def test_creates_building_floor_room_tree(self):
        db = _FakeGroupDb()
        host = _host("SU5-D206-TEMP")
        room = auto_group_host(db, host)
        self.assertEqual(room.name, "SU5-D206")
        self.assertEqual(room.parent.name, "2 этаж")
        self.assertEqual(room.parent.parent.name, "SU5")
        self.assertTrue(all(group.is_auto for group in db.groups))
        self.assertIs(host.group, room)

    def test_second_pc_reuses_the_tree(self):
        db = _FakeGroupDb()
        auto_group_host(db, _host("SU5-D206-TEMP"))
        room = auto_group_host(db, _host("SU5-D206-01"))
        self.assertEqual(db.names(), ["2 этаж", "SU5", "SU5-D206"])
        self.assertEqual(room.name, "SU5-D206")

    def test_every_building_gets_its_own_floor(self):
        db = _FakeGroupDb()
        su5 = auto_group_host(db, _host("SU5-D206-TEMP"))
        mr32 = auto_group_host(db, _host("MR32-211-01"))
        self.assertEqual(db.names(), ["2 этаж", "2 этаж", "MR32", "MR32-211", "SU5", "SU5-D206"])
        self.assertIsNot(su5.parent, mr32.parent)
        self.assertEqual((su5.parent.parent.name, mr32.parent.parent.name), ("SU5", "MR32"))

    def test_existing_manual_room_group_is_adopted_into_the_tree(self):
        manual = HostGroup(id=uuid.uuid4(), name="MR32-411", is_auto=False)
        db = _FakeGroupDb([manual])
        host = _host("MR32-411-01", manual)
        room = auto_group_host(db, host)
        self.assertIs(room, manual)
        self.assertFalse(manual.is_auto)
        self.assertEqual(manual.parent.name, "4 этаж")
        self.assertEqual(manual.parent.parent.name, "MR32")
        self.assertIs(host.group, manual)

    def test_host_in_another_manual_group_stays(self):
        manual = HostGroup(id=uuid.uuid4(), name="Преподавательские", is_auto=False)
        db = _FakeGroupDb([manual])
        host = _host("SU5-D206-TEMP", manual)
        self.assertIsNone(auto_group_host(db, host))
        self.assertIs(host.group, manual)
        self.assertEqual(db.names(), ["Преподавательские"])

    def test_find_group_by_name_prefers_top_level_and_refuses_ambiguity(self):
        db = _FakeGroupDb()
        auto_group_host(db, _host("SU5-D206-TEMP"))
        auto_group_host(db, _host("MR32-211-01"))
        self.assertEqual(find_group_by_name(db, "SU5-D206").name, "SU5-D206")
        self.assertIsNone(find_group_by_name(db, "SU5").parent_id)
        self.assertIsNone(find_group_by_name(db, "2 этаж"))  # есть в двух корпусах
        self.assertIsNone(find_group_by_name(db, "нет такой"))


class NestedInventoryTests(unittest.TestCase):
    def test_room_floor_building_are_nested_ansible_groups(self):
        su5 = HostGroup(id=uuid.uuid4(), name="SU5", is_auto=True)
        su5_floor = HostGroup(id=uuid.uuid4(), name="2 этаж", is_auto=True, parent=su5)
        su5_room = HostGroup(id=uuid.uuid4(), name="SU5-D206", is_auto=True, parent=su5_floor)
        mr32 = HostGroup(id=uuid.uuid4(), name="MR32", is_auto=True)
        mr32_floor = HostGroup(id=uuid.uuid4(), name="2 этаж", is_auto=True, parent=mr32)
        mr32_room = HostGroup(id=uuid.uuid4(), name="MR32-211", is_auto=True, parent=mr32_floor)
        hosts = [_host("SU5-D206-TEMP", su5_room), _host("MR32-211-01", mr32_room)]

        children = build_inventory_dict(_HostsDb(hosts))["all"]["children"]
        self.assertIn(str(hosts[0].id), children["SU5-D206"]["hosts"])
        # «2 этаж» в двух корпусах, а имена групп в Ansible глобальные — поэтому с путём.
        self.assertEqual(children["SU5 / 2 этаж"]["children"], {"SU5-D206": {}})
        self.assertEqual(children["MR32 / 2 этаж"]["children"], {"MR32-211": {}})
        self.assertEqual(children["SU5"]["children"], {"SU5 / 2 этаж": {}})
        self.assertNotIn("2 этаж", children)

    def test_unique_floor_name_stays_short(self):
        su5 = HostGroup(id=uuid.uuid4(), name="SU5", is_auto=True)
        floor = HostGroup(id=uuid.uuid4(), name="2 этаж", is_auto=True, parent=su5)
        room = HostGroup(id=uuid.uuid4(), name="SU5-D206", is_auto=True, parent=floor)
        children = build_inventory_dict(_HostsDb([_host("SU5-D206-TEMP", room)]))["all"]["children"]
        self.assertEqual(children["SU5"]["children"], {"2 этаж": {}})


if __name__ == "__main__":
    unittest.main()
