import unittest
import uuid

from models.host import Host, HostGroup, HostOS
from services.host_grouping import auto_group_host, parse_host_name, should_move
from services.inventory_generator import build_inventory_dict


class _GroupResult:
    def __init__(self, group):
        self._group = group

    def scalar_one_or_none(self):
        return self._group


class _FakeGroupDb:
    """Just enough of a Session for auto_group_host: groups looked up by name."""

    def __init__(self, groups=()):
        self.groups = {group.name: group for group in groups}

    def execute(self, query):
        return _GroupResult(self.groups.get(query.whereclause.right.value))

    def add(self, group):
        self.groups[group.name] = group

    def flush(self):
        for group in self.groups.values():
            if group.id is None:
                group.id = uuid.uuid4()
            if group.parent is not None:
                group.parent_id = group.parent.id


def _host(name, group=None):
    host = Host(id=uuid.uuid4(), hostname=name, ip_address="10.152.128.88", os=HostOS.windows_11, ssh_port=22)
    if group is not None:
        host.group = group
        host.group_id = group.id
    return host


class HostNameTests(unittest.TestCase):
    def test_building_room_floor_from_the_name(self):
        parts = parse_host_name("SU5-D206-TEMP")
        self.assertEqual((parts.building, parts.room, parts.floor), ("SU5", "D206", "2"))
        self.assertEqual((parts.building_group, parts.floor_group, parts.room_group), ("SU5", "SU5 2 этаж", "SU5-D206"))

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
        self.assertEqual(room.parent.name, "SU5 2 этаж")
        self.assertEqual(room.parent.parent.name, "SU5")
        self.assertTrue(all(group.is_auto for group in db.groups.values()))
        self.assertIs(host.group, room)

    def test_second_pc_reuses_the_tree(self):
        db = _FakeGroupDb()
        auto_group_host(db, _host("SU5-D206-TEMP"))
        room = auto_group_host(db, _host("SU5-D206-01"))
        self.assertEqual(sorted(db.groups), ["SU5", "SU5 2 этаж", "SU5-D206"])
        self.assertEqual(room.name, "SU5-D206")

    def test_existing_manual_room_group_is_adopted_into_the_tree(self):
        manual = HostGroup(id=uuid.uuid4(), name="MR32-411", is_auto=False)
        db = _FakeGroupDb([manual])
        host = _host("MR32-411-01", manual)
        room = auto_group_host(db, host)
        self.assertIs(room, manual)
        self.assertFalse(manual.is_auto)
        self.assertEqual(manual.parent.name, "MR32 4 этаж")
        self.assertIs(host.group, manual)

    def test_host_in_another_manual_group_stays(self):
        manual = HostGroup(id=uuid.uuid4(), name="Преподавательские", is_auto=False)
        db = _FakeGroupDb([manual])
        host = _host("SU5-D206-TEMP", manual)
        self.assertIsNone(auto_group_host(db, host))
        self.assertIs(host.group, manual)
        self.assertEqual(list(db.groups), ["Преподавательские"])


class NestedInventoryTests(unittest.TestCase):
    def test_room_floor_building_are_nested_ansible_groups(self):
        building = HostGroup(id=uuid.uuid4(), name="SU5", is_auto=True)
        floor = HostGroup(id=uuid.uuid4(), name="SU5 2 этаж", is_auto=True, parent=building)
        room = HostGroup(id=uuid.uuid4(), name="SU5-D206", is_auto=True, parent=floor)
        host = _host("SU5-D206-TEMP", room)

        class _Db:
            def execute(self, _query):
                class _R:
                    def scalars(self):
                        return self

                    def all(self):
                        return [host]
                return _R()

        children = build_inventory_dict(_Db())["all"]["children"]
        self.assertIn(str(host.id), children["SU5-D206"]["hosts"])
        self.assertEqual(children["SU5 2 этаж"]["children"], {"SU5-D206": {}})
        self.assertEqual(children["SU5"]["children"], {"SU5 2 этаж": {}})


if __name__ == "__main__":
    unittest.main()
