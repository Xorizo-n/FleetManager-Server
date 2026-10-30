import unittest
from types import SimpleNamespace
from unittest.mock import patch
import uuid
from services.printer_monitor import supply_items, poll_printer
from routers.printers import PrinterInput, PrinterOut, router, readers, editors
from database import Base, get_db
from dependencies import get_current_user
from models.user import UserRole
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from models.printer import Printer
from pydantic import ValidationError


class PrinterMonitorTests(unittest.TestCase):
    def test_supply_percent_and_unknown_values(self):
        rows = {(1, 1): {6: "Black", 8: "100", 9: "63"},
                (1, 2): {6: "Cyan", 8: "100", 9: "-3"},
                (1, 3): {6: "Magenta", 8: "0", 9: "0"},
                (1, 4): {6: "Yellow", 8: "100", 9: "101"}}
        self.assertEqual([s["percent"] for s in supply_items(rows)], [63, None, None, None])

    def test_address_rejects_unroutable_and_invalid_inputs(self):
        for address in ("169.254.1.1", "127.0.0.1", "224.0.0.1", "::1", "example.com"):
            with self.subTest(address=address), self.assertRaises(ValidationError):
                PrinterInput(name="Printer", address=address)
        self.assertEqual(PrinterInput(name=" P ", address="10.152.128.200").name, "P")

    @patch("services.printer_monitor.asyncio.run")
    @patch("services.printer_monitor.asyncio.wait_for", new=lambda coro, timeout: coro)
    @patch("services.printer_monitor.decrypt_secret", return_value="public")
    @patch("services.printer_monitor.redis.Redis.from_url")
    @patch("services.printer_monitor.SessionLocal")
    def test_failed_poll_preserves_last_data(self, session, redis_factory, decrypt, run):
        printer = SimpleNamespace(address="10.0.0.1", community_encrypted="secret", data={"pages": 12}, last_seen_at="earlier", status="online", last_checked_at=None)
        db = session.return_value.__enter__.return_value
        db.get.return_value = printer
        redis_factory.return_value.lock.return_value.acquire.return_value = True
        def timeout(coro):
            coro.close()
            raise TimeoutError()
        run.side_effect = timeout
        poll_printer.run(str(uuid.uuid4()))
        self.assertEqual(printer.status, "unreachable")
        self.assertEqual(printer.data, {"pages": 12})
        self.assertEqual(printer.last_seen_at, "earlier")
        db.commit.assert_called_once()

    def test_response_never_exposes_community(self):
        self.assertNotIn("community", PrinterOut.model_fields)
        self.assertNotIn("community_encrypted", PrinterOut.model_fields)


class PrinterApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Printer.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        app = FastAPI(); app.include_router(router)
        def db_override():
            with self.sessions() as db: yield db
        app.dependency_overrides[get_db] = db_override
        user = SimpleNamespace(id=None)
        app.dependency_overrides[readers] = lambda: user
        app.dependency_overrides[editors] = lambda: user
        self.client = TestClient(app)
        self.audit = patch("routers.printers.record_audit"); self.audit.start()

    def tearDown(self):
        self.audit.stop(); self.engine.dispose()

    def test_viewer_can_read_but_cannot_start_discovery(self):
        app = FastAPI(); app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=None, role=UserRole.viewer)
        client = TestClient(app)
        with patch("routers.printers.discovery_status", return_value={"status": "never"}):
            self.assertEqual(client.get("/printers/discovery/status").status_code, 200)
        self.assertEqual(client.post("/printers/discovery").status_code, 403)

    def test_create_change_address_and_duplicate(self):
        payload = {"name": "Printer", "address": "10.1.2.3", "community": "private"}
        response = self.client.post("/printers", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertNotIn("community", response.text)
        pid = response.json()["id"]
        with self.sessions() as db:
            printer = db.get(Printer, uuid.UUID(pid)); self.assertNotEqual(printer.community_encrypted, "private")
            printer.data = {"pages": 12}; printer.status = "online"; db.commit()
        self.assertEqual(self.client.post("/printers", json=payload).status_code, 409)
        response = self.client.put(f"/printers/{pid}", json={"name": "Printer", "address": "10.1.2.4"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "unknown")
        self.assertIsNone(response.json()["data"])


if __name__ == "__main__": unittest.main()
