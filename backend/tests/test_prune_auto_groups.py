import unittest
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from database import Base
from models.credential import Credential, CredentialType
from models.host import Host, HostGroup, HostOS
from models.playbook import PlaybookRepo, PlaybookSchedule
from services.host_grouping import auto_group_host, prune_empty_auto_groups


class PruneEmptyAutoGroupsTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)

    def host(self, name, group=None):
        host = Host(id=uuid.uuid4(), hostname=name, ip_address="10.152.5.66", os=HostOS.windows_11, ssh_port=22, group=group)
        self.db.add(host)
        self.db.flush()
        return host

    def tree(self, *room_names):
        """SU5 > 2 этаж > rooms, created the way auto grouping does it."""
        rooms = {}
        for room in room_names:
            host = self.host(f"{room}-W01")
            rooms[room] = auto_group_host(self.db, host)
        self.db.commit()
        return rooms

    def names(self):
        return sorted(self.db.scalars(select(HostGroup.name)))

    def test_room_left_without_hosts_is_deleted_with_its_empty_floor_and_building(self):
        self.tree("SU5-K204")
        self.db.delete(self.db.query(Host).one())
        self.db.flush()

        self.assertEqual(sorted(prune_empty_auto_groups(self.db)), ["2 этаж", "SU5", "SU5-K204"])
        self.assertEqual(self.names(), [])

    def test_only_the_emptied_room_goes_when_the_floor_has_other_rooms(self):
        self.tree("SU5-K204", "SU5-K205")
        self.db.delete(self.db.query(Host).filter(Host.hostname == "SU5-K204-W01").one())
        self.db.flush()

        self.assertEqual(prune_empty_auto_groups(self.db), ["SU5-K204"])
        self.assertEqual(self.names(), ["2 этаж", "SU5", "SU5-K205"])

    def test_renamed_host_leaves_its_old_room_behind(self):
        rooms = self.tree("SU5-K204")
        host = self.db.query(Host).one()
        host.hostname = "SU5-K304-W01"
        auto_group_host(self.db, host)
        self.db.flush()

        # K304 is on the third floor, so "2 этаж" is left empty too
        self.assertEqual(prune_empty_auto_groups(self.db), ["SU5-K204", "2 этаж"])
        self.assertEqual(host.group.name, "SU5-K304")
        self.assertNotIn(rooms["SU5-K204"].name, self.names())

    def test_groups_an_administrator_configured_are_kept(self):
        rooms = self.tree("SU5-K204", "SU5-K205")
        credential = Credential(id=uuid.uuid4(), name="room key", login="admin", type=CredentialType.password, secret_encrypted="x")
        self.db.add(credential)
        rooms["SU5-K204"].credential_id = credential.id
        repo = PlaybookRepo(id=uuid.uuid4(), name="repo", git_url="https://example.invalid/repo.git", local_path="/tmp/repo")
        self.db.add(repo)
        self.db.flush()
        self.db.add(PlaybookSchedule(id=uuid.uuid4(), repo_id=repo.id, playbook_name="p.yml", cron_expression="0 3 * * *",
                                     host_group_ids=[str(rooms["SU5-K205"].id)]))
        self.db.query(Host).delete()
        self.db.flush()

        self.assertEqual(prune_empty_auto_groups(self.db), [])

    def test_manual_groups_are_never_deleted(self):
        self.db.add(HostGroup(id=uuid.uuid4(), name="Преподаватели", is_auto=False))
        self.db.flush()

        self.assertEqual(prune_empty_auto_groups(self.db), [])
        self.assertEqual(self.names(), ["Преподаватели"])

    def test_room_with_hosts_stays(self):
        self.tree("SU5-K204")
        self.assertEqual(prune_empty_auto_groups(self.db), [])
        self.assertEqual(self.names(), ["2 этаж", "SU5", "SU5-K204"])


if __name__ == "__main__":
    unittest.main()
