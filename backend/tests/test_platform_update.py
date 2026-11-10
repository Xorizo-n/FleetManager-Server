import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from database import get_db
from dependencies import get_current_user
from models.user import UserRole
from routers import platform_update
from services.platform_maintenance import maintenance


class PlatformApiTests(unittest.TestCase):
    def app(self, role=UserRole.admin):
        app = FastAPI()
        app.include_router(platform_update.router)
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4(), role=role)
        app.dependency_overrides[get_db] = lambda: None
        return TestClient(app)

    @patch("routers.platform_update.call")
    def test_all_operations_are_admin_only(self, call):
        for role in (UserRole.viewer, UserRole.operator, UserRole.monitoring):
            client = self.app(role)
            self.assertEqual(client.get("/settings/platform").status_code, 403)
            for action, data in (("check", {}), ("install", {"version": "v1.0.0"}), ("restore", {"confirm_data_loss": True})):
                self.assertEqual(client.post("/settings/platform/" + action, json=data).status_code, 403)
        call.assert_not_called()

    @patch("routers.platform_update.record_audit")
    @patch("routers.platform_update.call", return_value={"busy": True})
    def test_install_records_initiator(self, call, audit):
        self.assertEqual(self.app().post("/settings/platform/install", json={"version": "v1.0.0"}).status_code, 202)
        self.assertEqual(call.call_args.args[2]["version"], "v1.0.0")
        self.assertIn("actor", call.call_args.args[2])
        audit.assert_called_once()

    @patch("routers.platform_update.call")
    def test_restore_requires_explicit_confirmation(self, call):
        self.assertEqual(self.app().post("/settings/platform/restore", json={"confirm_data_loss": False}).status_code, 400)
        call.assert_not_called()

    @patch("routers.platform_update.UpdaterConnection")
    def test_unavailable_service_is_503(self, connection):
        connection.return_value.request.side_effect = OSError("missing socket")
        self.assertEqual(self.app().get("/settings/platform").status_code, 503)

    def test_maintenance_blocks_agent_and_user_requests_but_keeps_update_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            flag = Path(tmp, "maintenance")
            app = FastAPI(); app.middleware("http")(maintenance)
            for path in ("/agent/heartbeat", "/hosts", "/health", "/settings/platform"):
                app.add_api_route(path, lambda: {"ok": True}, methods=["GET", "POST"])
            client = TestClient(app)
            with patch("services.platform_maintenance.settings.platform_maintenance_file", str(flag)):
                self.assertEqual(client.post("/agent/heartbeat").status_code, 200)
                flag.touch()
                self.assertEqual(client.post("/agent/heartbeat").status_code, 503)
                self.assertEqual(client.get("/hosts").headers["retry-after"], "30")
                self.assertEqual(client.get("/health").status_code, 200)
                self.assertEqual(client.get("/settings/platform").status_code, 200)
