import json
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models.printer import Printer
from services.printer_discovery import add_results, parse_result, select_hosts, discover_printers


class PrinterDiscoveryTests(unittest.TestCase):
    def test_select_one_fresh_online_host_per_named_room(self):
        def host(name, seen):
            return SimpleNamespace(id=uuid.uuid4(), hostname=name, last_seen_at=seen)
        older = host("SU5-D206-W01", datetime(2026, 1, 1, tzinfo=timezone.utc))
        newer = host("SU5-D206-TEMP", datetime(2026, 1, 2, tzinfo=timezone.utc))
        another = host("SU5-D203-W01", None)
        selection = select_hosts([older, newer, another, host("unknown", None)])
        self.assertEqual(set(selection), {"SU5-D206", "SU5-D203"})
        self.assertEqual(selection["SU5-D206"], [newer, older])
        self.assertEqual(selection["SU5-D203"], [another])

    def test_parse_validates_subnet_and_printer_addresses(self):
        payload = {"subnet": "10.152.128.64/26", "printers": [{"address": "10.152.128.80", "name": "su5-d203-p01", "model": "HP"}, {"address": "10.152.128.200"}]}
        subnet, printers = parse_result("diagnostic\nFM_PRINTER_DISCOVERY=" + json.dumps(payload))
        self.assertEqual(subnet, "10.152.128.64/26")
        self.assertEqual([p["address"] for p in printers], ["10.152.128.80"])
        with self.assertRaises(ValueError): parse_result("FM_PRINTER_DISCOVERY={}")
        payload["subnet"] = "10.152.0.0/16"
        with self.assertRaises(ValueError): parse_result("FM_PRINTER_DISCOVERY=" + json.dumps(payload))

    def test_add_preserves_existing_and_assigns_correct_room(self):
        engine = create_engine("sqlite://", poolclass=StaticPool)
        Printer.__table__.create(engine)
        with sessionmaker(bind=engine)() as db:
            existing = Printer(name="Manual", address="10.152.128.81", location="Manual room", community_encrypted="custom")
            db.add(existing); db.commit()
            findings = {
                "10.152.128.80": [("SU5-D206", {"name": "su5-d203-p01", "model": "M430"})],
                "10.152.128.81": [("SU5-D206", {"name": "another", "model": "M430"})],
                "10.152.128.82": [("SU5-D206", {"name": "HP", "model": "M479"}), ("SU5-D203", {"name": "HP", "model": "M479"})],
                "10.152.128.83": [("SU5-D206", {"name": "HP", "model": "M479"})],
            }
            self.assertEqual(len(add_results(db, findings)), 3)
            self.assertEqual(add_results(db, findings), [])
            records = {p.address: p for p in db.query(Printer).all()}
            self.assertEqual(records["10.152.128.80"].location, "SU5-D203")
            self.assertEqual(records["10.152.128.81"].location, "Manual room")
            self.assertEqual(records["10.152.128.81"].community_encrypted, "custom")
            self.assertIn("нескольких", records["10.152.128.82"].location)
            self.assertIn("уточнить", records["10.152.128.83"].location)
        engine.dispose()

    @patch("services.printer_discovery.poll_printer.delay")
    @patch("services.printer_discovery.add_results", return_value=["printer-id"])
    @patch("services.printer_discovery.run_ansible")
    @patch("services.printer_discovery.build_full_inventory", return_value={"all": {}})
    @patch("services.printer_discovery.SessionLocal")
    @patch("services.printer_discovery.store")
    def test_discovery_runs_one_pc_and_queues_new_printer(self, store, sessions, inventory, run, add, poll):
        client = store.return_value; client.get.return_value = "token"
        host = SimpleNamespace(id=uuid.uuid4(), hostname="SU5-D206-TEMP", last_seen_at=None)
        db = sessions.return_value.__enter__.return_value
        db.query.return_value.all.return_value = [host]
        result = {"subnet": "10.152.128.64/26", "printers": [{"address": "10.152.128.80", "name": "SU5-D203-P01", "model": "M430"}]}
        run.return_value.events = [{"event": "runner_on_ok", "event_data": {"host": str(host.id), "res": {"rc": 0, "stdout": "FM_PRINTER_DISCOVERY=" + json.dumps(result)}}}]
        discover_printers.run("token")
        self.assertEqual(inventory.call_args.args[1], [host.id])
        self.assertEqual(add.call_args.args[1]["10.152.128.80"][0][0], "SU5-D206")
        poll.assert_called_once_with("printer-id")
        final = json.loads(client.set.call_args.args[1])
        self.assertEqual((final["status"], final["rooms_scanned"], final["added"]), ("completed", 1, 1))
        self.assertEqual(client.eval.call_count, 2)

    @patch("services.printer_discovery.poll_printer.delay")
    @patch("services.printer_discovery.add_results", return_value=[])
    @patch("services.printer_discovery.run_ansible")
    @patch("services.printer_discovery.build_full_inventory", return_value={"all": {}})
    @patch("services.printer_discovery.SessionLocal")
    @patch("services.printer_discovery.store")
    def test_retries_all_pcs_until_room_succeeds(self, store, sessions, inventory, run, add, poll):
        from models.host import HostStatus
        client = store.return_value; client.get.return_value = "token"
        def host(name, status, day):
            return SimpleNamespace(id=uuid.uuid4(), hostname=name, status=status, last_seen_at=datetime(2026, 1, day, tzinfo=timezone.utc))
        first = host("SU5-D206-W01", HostStatus.online, 3)
        second = host("SU5-D206-W02", HostStatus.online, 2)
        last = host("SU5-D206-W03", HostStatus.offline, 1)
        other = host("SU5-D203-W01", HostStatus.online, 1)
        db = sessions.return_value.__enter__.return_value
        db.query.return_value.all.return_value = [first, second, last, other]
        good = "FM_PRINTER_DISCOVERY=" + json.dumps({"subnet": "10.152.128.64/26", "printers": []})
        def event(h, name, out=""):
            return {"event": name, "event_data": {"host": str(h.id), "res": {"rc": 0, "stdout": out}}}
        run.side_effect = [SimpleNamespace(events=[event(first, "runner_on_unreachable"), event(other, "runner_on_ok", good)]),
                           SimpleNamespace(events=[event(second, "runner_on_ok", "bad output")]),
                           SimpleNamespace(events=[event(last, "runner_on_ok", good)])]
        discover_printers.run("token")
        self.assertEqual([set(call.args[1]) for call in inventory.call_args_list], [{first.id, other.id}, {second.id}, {last.id}])
        final = json.loads(client.set.call_args.args[1])
        self.assertEqual(final["rooms_scanned"], 2)
        self.assertEqual(final["failed_rooms"], [])
        self.assertEqual(run.call_count, 3)

    @patch("services.printer_discovery.discover_printers.delay")
    @patch("services.printer_discovery.store")
    def test_no_overlapping_discoveries(self, factory, delay):
        from services.printer_discovery import enqueue_discovery
        client = factory.return_value
        client.set.return_value = False
        self.assertFalse(enqueue_discovery())
        delay.assert_not_called()


if __name__ == "__main__": unittest.main()
