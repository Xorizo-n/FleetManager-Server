import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from main import app
from schemas.host import AccessChangeRequest
from services import access_change as ac
from services.host_grouping import keeps_ssh_access

BUILDING, FLOOR, ROOM, OTHER_ROOM, MANUAL = (uuid.uuid4() for _ in range(5))
BUILDING_KEY, ROOM_KEY, NEW_KEY, OWN_KEY, AGENT_KEY = (uuid.uuid4() for _ in range(5))

# group id -> (parent_id, credential_id)
GROUPS = {
    BUILDING: (None, BUILDING_KEY),
    FLOOR: (BUILDING, None),
    ROOM: (FLOOR, None),
    OTHER_ROOM: (FLOOR, ROOM_KEY),
    MANUAL: (None, None),
}


def host(own=None, group=ROOM):
    return (uuid.uuid4(), own, group)


class EffectiveCredentialTests(unittest.TestCase):
    def test_own_credential_wins(self):
        self.assertEqual(ac.effective_credential(OWN_KEY, ROOM, GROUPS), OWN_KEY)

    def test_nearest_group_credential_is_inherited(self):
        self.assertEqual(ac.effective_credential(None, ROOM, GROUPS), BUILDING_KEY)
        self.assertEqual(ac.effective_credential(None, OTHER_ROOM, GROUPS), ROOM_KEY)

    def test_no_credential(self):
        self.assertIsNone(ac.effective_credential(None, MANUAL, GROUPS))
        self.assertIsNone(ac.effective_credential(None, None, GROUPS))

    def test_cycle_terminates(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        self.assertIsNone(ac.effective_credential(None, a, {a: (b, None), b: (a, None)}))


class PlanTests(unittest.TestCase):
    def test_host_credential_change_is_checked(self):
        inherited, own = host(), host(own=OWN_KEY)
        plans = ac.plan_host_credential([inherited, own], NEW_KEY, GROUPS, set())
        self.assertEqual([(p.old_credential, p.new_credential, p.needs_check) for p in plans],
                         [(BUILDING_KEY, NEW_KEY, True), (OWN_KEY, NEW_KEY, True)])

    def test_setting_the_credential_already_used_needs_no_check(self):
        plans = ac.plan_host_credential([host()], BUILDING_KEY, GROUPS, set())
        self.assertFalse(plans[0].needs_check)

    def test_back_to_group_credential_is_checked(self):
        plans = ac.plan_host_credential([host(own=OWN_KEY)], None, GROUPS, set())
        self.assertEqual((plans[0].new_credential, plans[0].needs_check), (BUILDING_KEY, True))

    def test_agent_key_is_never_replaced(self):
        plans = ac.plan_host_credential([host(own=AGENT_KEY)], NEW_KEY, GROUPS, {AGENT_KEY})
        self.assertIsNotNone(plans[0].skip_reason)
        self.assertFalse(plans[0].needs_check)

    def test_move_checks_only_hosts_whose_credential_changes(self):
        inherits, agent, same = host(group=ROOM), host(own=AGENT_KEY, group=ROOM), host(group=FLOOR)
        plans = ac.plan_move([inherits, agent, same], OTHER_ROOM, GROUPS)
        self.assertEqual([p.needs_check for p in plans], [True, False, True])
        plans = ac.plan_move([host(group=ROOM)], FLOOR, GROUPS)
        self.assertFalse(plans[0].needs_check)  # и там, и там учётка корпуса

    def test_move_out_of_groups_loses_inherited_credential(self):
        plans = ac.plan_move([host()], None, GROUPS)
        self.assertEqual((plans[0].new_credential, plans[0].needs_check), (None, True))

    def test_group_credential_affects_only_inheriting_hosts_below(self):
        inherits = host(group=ROOM)
        own = host(own=OWN_KEY, group=ROOM)
        closer_group = host(group=OTHER_ROOM)
        outside = host(group=MANUAL)
        plans = ac.plan_group_credential([inherits, own, closer_group, outside], BUILDING, NEW_KEY, GROUPS)
        self.assertEqual([p.host_id for p in plans], [inherits[0]])
        self.assertEqual((plans[0].old_credential, plans[0].new_credential), (BUILDING_KEY, NEW_KEY))

    def test_clearing_a_group_credential_falls_back_to_the_parent(self):
        plans = ac.plan_group_credential([host(group=OTHER_ROOM)], OTHER_ROOM, None, GROUPS)
        self.assertEqual((plans[0].old_credential, plans[0].new_credential), (ROOM_KEY, BUILDING_KEY))


class _Db:
    def __init__(self, hosts=(), groups=()):
        self.objects = {obj.id: obj for obj in [*hosts, *groups]}
        self.committed = False

    def get(self, _model, object_id):
        return self.objects.get(object_id)

    def commit(self):
        self.committed = True


def host_obj(credential_id=None, group_id=ROOM):
    return SimpleNamespace(id=uuid.uuid4(), credential_id=credential_id, group_id=group_id)


class ApplyTests(unittest.TestCase):
    def _apply(self, db, spec, plans, passed):
        with patch.object(ac, "hosts_by_ids", lambda _db, ids: [db.objects[i] for i in ids]):
            return ac.apply_change(db, spec, plans, passed)

    def test_host_credential_kept_where_login_failed(self):
        ok, bad, unaffected = host_obj(), host_obj(), host_obj()
        db = _Db([ok, bad, unaffected])
        plans = [
            ac.HostPlan(ok.id, BUILDING_KEY, NEW_KEY, True),
            ac.HostPlan(bad.id, BUILDING_KEY, NEW_KEY, True),
            ac.HostPlan(unaffected.id, NEW_KEY, NEW_KEY, False),
        ]
        summary = self._apply(db, {"action": ac.SET_HOST_CREDENTIAL, "credential_id": str(NEW_KEY)}, plans, {ok.id})
        self.assertEqual((ok.credential_id, bad.credential_id, unaffected.credential_id), (NEW_KEY, None, NEW_KEY))
        self.assertEqual((summary["applied"], summary["failed"]), (2, 1))
        self.assertTrue(db.committed)

    def test_failed_hosts_stay_in_their_group(self):
        ok, bad = host_obj(), host_obj()
        db = _Db([ok, bad])
        plans = [ac.HostPlan(ok.id, BUILDING_KEY, ROOM_KEY, True), ac.HostPlan(bad.id, BUILDING_KEY, ROOM_KEY, True)]
        self._apply(db, {"action": ac.MOVE_TO_GROUP, "group_id": str(OTHER_ROOM)}, plans, {ok.id})
        self.assertEqual((ok.group_id, bad.group_id), (OTHER_ROOM, ROOM))

    def test_skipped_agent_host_is_untouched(self):
        agent = host_obj(credential_id=AGENT_KEY)
        db = _Db([agent])
        plans = [ac.HostPlan(agent.id, AGENT_KEY, AGENT_KEY, False, "ключ агента")]
        self._apply(db, {"action": ac.SET_HOST_CREDENTIAL, "credential_id": str(NEW_KEY)}, plans, set())
        self.assertEqual(agent.credential_id, AGENT_KEY)

    def test_group_credential_pins_previous_credential_on_failed_hosts(self):
        group = SimpleNamespace(id=BUILDING, credential_id=BUILDING_KEY)
        ok, bad, had_none = host_obj(), host_obj(), host_obj()
        db = _Db([ok, bad, had_none], [group])
        plans = [
            ac.HostPlan(ok.id, BUILDING_KEY, NEW_KEY, True),
            ac.HostPlan(bad.id, BUILDING_KEY, NEW_KEY, True),
            ac.HostPlan(had_none.id, None, NEW_KEY, True),
        ]
        summary = self._apply(db, {"action": ac.SET_GROUP_CREDENTIAL, "group_id": str(BUILDING), "credential_id": str(NEW_KEY)}, plans, {ok.id})
        self.assertEqual(group.credential_id, NEW_KEY)
        self.assertEqual((ok.credential_id, bad.credential_id, had_none.credential_id), (None, BUILDING_KEY, None))
        self.assertEqual((summary["pinned"], summary["without_previous"]), (1, 1))


class VerifyTests(unittest.TestCase):
    def test_host_left_without_credential_fails_without_ansible(self):
        plan = ac.HostPlan(uuid.uuid4(), BUILDING_KEY, None, True)
        with patch.object(ac, "run_ansible") as run:
            results = ac.verify_logins(None, [plan])
        run.assert_not_called()
        self.assertIsNotNone(results[plan.host_id])

    def test_no_checks_no_ansible(self):
        with patch.object(ac, "run_ansible") as run:
            self.assertEqual(ac.verify_logins(None, [ac.HostPlan(uuid.uuid4(), NEW_KEY, NEW_KEY, False)]), {})
        run.assert_not_called()


class AutoGroupingTests(unittest.TestCase):
    def test_working_inherited_credential_is_not_changed(self):
        self.assertFalse(keeps_ssh_access(None, BUILDING_KEY, ROOM_KEY))
        self.assertFalse(keeps_ssh_access(None, BUILDING_KEY, None))

    def test_moves_that_keep_access_are_allowed(self):
        self.assertTrue(keeps_ssh_access(None, BUILDING_KEY, BUILDING_KEY))
        self.assertTrue(keeps_ssh_access(AGENT_KEY, BUILDING_KEY, ROOM_KEY))  # своя учётка
        self.assertTrue(keeps_ssh_access(None, None, ROOM_KEY))  # доступа не было


class RequestTests(unittest.TestCase):
    def test_host_actions_need_hosts(self):
        with self.assertRaises(ValidationError):
            AccessChangeRequest(action="set_host_credential", credential_id=NEW_KEY)

    def test_group_credential_needs_group(self):
        with self.assertRaises(ValidationError):
            AccessChangeRequest(action="set_group_credential", credential_id=NEW_KEY)

    def test_move_takes_group_or_name_not_both(self):
        with self.assertRaises(ValidationError):
            AccessChangeRequest(action="move_to_group", host_ids=[uuid.uuid4()], group_id=ROOM, group_name="X")
        self.assertIsNone(AccessChangeRequest(action="move_to_group", host_ids=[uuid.uuid4()]).group_id)

    def test_route_registered(self):
        routes = {(r.path, m) for r in app.routes for m in getattr(r, "methods", ())}
        self.assertIn(("/hosts/access-changes", "POST"), routes)


if __name__ == "__main__":
    unittest.main()
