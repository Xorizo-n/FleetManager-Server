"""Host tags: rule by manufacturer + model, manual tag priority, playbook targets by tag."""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.host import Host, HostOS, HostTag, HostTagRule
from models.playbook import PlaybookRepo, PlaybookSchedule
from routers.host_tags import assign_tag, delete_tag, list_models, list_tags, set_rule
from schemas.host_tag import HostTagAssign, HostTagRuleSet
from schemas.playbook import PlaybookRunRequest, PlaybookScheduleUpdate
from services.host_tags import apply_rule, model_key, retag_hosts, rule_map
from services.inventory_generator import resolve_target_host_ids
from services.schedule_targets import schedule_out

MSI = "Micro-Star International Co., Ltd."
MSI_MODEL = "PRO H610 AP272 14M (MS-AF83)"
USER = SimpleNamespace(id=None)


class RuleMatchTests(unittest.TestCase):
    def test_key_ignores_case_and_extra_spaces(self):
        self.assertEqual(model_key("  Micro-Star  International Co., Ltd. ", "pro h610 ap272 14m (ms-af83)"), model_key(MSI, MSI_MODEL))

    def test_missing_model_has_no_key(self):
        self.assertIsNone(model_key("IRBIS", None))
        self.assertIsNone(model_key(" ", "GDCS7001HA"))

    def test_rule_sets_tag_but_not_over_manual(self):
        tag = uuid.uuid4()
        rules = rule_map([SimpleNamespace(manufacturer="IRBIS", model="GDCS7001HA", tag_id=tag)])
        host = Host(hw_manufacturer="irbis", hw_model="GDCS7001HA", tag_id=None, tag_manual=False)
        self.assertTrue(apply_rule(host, rules))
        self.assertEqual(host.tag_id, tag)
        self.assertFalse(apply_rule(host, rules))

        manual = Host(hw_manufacturer="IRBIS", hw_model="GDCS7001HA", tag_id=None, tag_manual=True)
        self.assertFalse(apply_rule(manual, rules))
        self.assertIsNone(manual.tag_id)

    def test_model_without_rule_loses_rule_tag(self):
        host = Host(hw_manufacturer="Red Hat", hw_model="KVM", tag_id=uuid.uuid4(), tag_manual=False)
        self.assertTrue(apply_rule(host, {}))
        self.assertIsNone(host.tag_id)

    def test_assign_rejects_tag_together_with_by_rule(self):
        with self.assertRaises(ValidationError):
            HostTagAssign(host_ids=[uuid.uuid4()], tag_id=uuid.uuid4(), by_rule=True)


class TagDbTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.students = self.tag("Студенты")
        self.admins = self.tag("Администрация")
        self.db.add_all([
            HostTagRule(manufacturer="IRBIS", model="GDCS7001HA", tag_id=self.students.id),
            HostTagRule(manufacturer=MSI, model=MSI_MODEL, tag_id=self.admins.id),
        ])
        self.db.commit()

    def tag(self, name):
        tag = HostTag(id=uuid.uuid4(), name=name)
        self.db.add(tag)
        self.db.flush()
        return tag

    def host(self, name, manufacturer, model, **values):
        host = Host(id=uuid.uuid4(), hostname=name, ip_address="10.152.5.66", os=HostOS.windows_11, ssh_port=22,
                    hw_manufacturer=manufacturer, hw_model=model, **values)
        self.db.add(host)
        self.db.flush()
        return host

    def test_retag_after_rule_change_keeps_manual_tags(self):
        pupil = self.host("SU5-K205-W01", "IRBIS", "GDCS7001HA")
        teacher = self.host("SU5-K205-W00", "IRBIS", "GDCS7001HA", tag_id=self.admins.id, tag_manual=True)
        office = self.host("SU5-A101-W01", MSI, MSI_MODEL)
        self.assertEqual(retag_hosts(self.db), 2)
        self.assertEqual((pupil.tag_id, teacher.tag_id, office.tag_id), (self.students.id, self.admins.id, self.admins.id))

        seminar = self.tag("Семинарские")
        self.db.commit()
        result = set_rule(HostTagRuleSet(manufacturer=" irbis ", model="GDCS7001HA", tag_id=seminar.id), None, self.db, USER)
        self.assertEqual(result.retagged, 1)
        self.assertEqual((pupil.tag_id, teacher.tag_id), (seminar.id, self.admins.id))
        self.assertEqual(self.db.query(HostTagRule).filter(HostTagRule.tag_id == seminar.id).count(), 1)
        self.assertEqual(self.db.query(HostTagRule).count(), 2)

        set_rule(HostTagRuleSet(manufacturer="IRBIS", model="GDCS7001HA", tag_id=None), None, self.db, USER)
        self.assertIsNone(pupil.tag_id)
        self.assertEqual(self.db.query(HostTagRule).count(), 1)

    def test_manual_tag_then_back_to_rule(self):
        pupil = self.host("SU5-K205-W01", "IRBIS", "GDCS7001HA")
        retag_hosts(self.db)
        assign_tag(HostTagAssign(host_ids=[pupil.id], tag_id=None), None, self.db, USER)
        self.assertEqual((pupil.tag_id, pupil.tag_manual), (None, True))
        self.assertEqual(retag_hosts(self.db), 0)
        assign_tag(HostTagAssign(host_ids=[pupil.id], by_rule=True), None, self.db, USER)
        self.assertEqual((pupil.tag_id, pupil.tag_manual), (self.students.id, False))

    def test_assign_unknown_host_is_404(self):
        with self.assertRaises(HTTPException) as ctx:
            assign_tag(HostTagAssign(host_ids=[uuid.uuid4()], tag_id=self.students.id), None, self.db, USER)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_deleting_tag_returns_its_manual_hosts_to_rules(self):
        pupil = self.host("SU5-K205-W01", "IRBIS", "GDCS7001HA", tag_id=self.admins.id, tag_manual=True)
        delete_tag(self.admins.id, None, self.db, USER)
        self.assertEqual((pupil.tag_id, pupil.tag_manual), (self.students.id, False))
        self.assertEqual(self.db.query(HostTagRule).count(), 1)

    def test_tag_used_by_schedule_is_not_deleted(self):
        repo = PlaybookRepo(id=uuid.uuid4(), name="r", git_url="x", local_path="/tmp/r")
        self.db.add(repo)
        self.db.add(PlaybookSchedule(repo_id=repo.id, playbook_name="a.yml", cron_expression="0 3 * * *", host_tag_ids=[str(self.students.id)]))
        self.db.commit()
        with self.assertRaises(HTTPException) as ctx:
            delete_tag(self.students.id, None, self.db, USER)
        self.assertEqual(ctx.exception.status_code, 409)
        counts = {t.name: t.schedule_count for t in list_tags(self.db, USER)}
        self.assertEqual(counts["Студенты"], 1)

    def test_models_list_merges_fleet_and_rules(self):
        self.host("SU5-K205-W01", "IRBIS", "GDCS7001HA")
        self.host("SU5-K205-W02", "IRBIS ", "GDCS7001HA", tag_manual=True)
        self.host("VM", "Red Hat", "KVM")
        models = {(m.manufacturer, m.model): m for m in list_models(self.db, USER)}
        irbis = models[("IRBIS", "GDCS7001HA")]
        self.assertEqual((irbis.host_count, irbis.manual_count, irbis.tag_id), (2, 1, self.students.id))
        self.assertIsNone(models[("Red Hat", "KVM")].rule_id)
        self.assertEqual(models[(MSI, MSI_MODEL)].host_count, 0)

    def test_tag_targets_expand_to_hosts(self):
        pupil = self.host("SU5-K205-W01", "IRBIS", "GDCS7001HA")
        office = self.host("SU5-A101-W01", MSI, MSI_MODEL)
        retag_hosts(self.db)
        self.db.commit()
        self.assertEqual(resolve_target_host_ids(self.db, [], [], [str(self.students.id)]), [str(pupil.id)])
        self.assertEqual(
            resolve_target_host_ids(self.db, [office.id], [], [self.students.id, self.admins.id]),
            [str(office.id), str(pupil.id)],
        )
        self.assertEqual(resolve_target_host_ids(self.db, [], [], []), [])


class PlaybookTagTargetTests(unittest.TestCase):
    def test_run_request_and_schedule_accept_tags(self):
        tag = uuid.uuid4()
        self.assertEqual(PlaybookRunRequest(repo_id=uuid.uuid4(), playbook_name="a.yml", host_tag_ids=[tag]).host_tag_ids, [tag])
        self.assertEqual(PlaybookScheduleUpdate(host_tag_ids=[tag]).model_dump(exclude_unset=True), {"host_tag_ids": [tag]})
        schedule = PlaybookSchedule(id=uuid.uuid4(), repo_id=uuid.uuid4(), playbook_name="a.yml", host_tag_ids=[str(tag), str(tag)],
                                    cron_expression="0 3 * * *", enabled=False, created_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
        self.assertEqual(schedule_out(schedule).host_tag_ids, [str(tag)])


if __name__ == "__main__":
    unittest.main()
