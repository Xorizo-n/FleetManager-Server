import unittest
import uuid

from pydantic import ValidationError

from schemas.agent import (
    AgentAlertRequest,
    AgentHeartbeatRequest,
    AgentRegisterRequest,
    AgentSoftware,
)
from datetime import datetime, timedelta, timezone

from services.agent_auth import CLONE_GUARD_WINDOW, hash_agent_token, is_machine_id_clone, issue_agent_token, verify_agent_token


class AgentApiContractTests(unittest.TestCase):
    def test_registration_requires_enrollment_token_and_machine_id(self):
        with self.assertRaises(ValidationError):
            AgentRegisterRequest(enrollment_token="", machine_id="", hostname="pc-01", os="windows_11")

    def test_registration_accepts_hostname_and_ip_fallback(self):
        payload = AgentRegisterRequest(
            enrollment_token="enrollment-secret-12345",
            machine_id=str(uuid.uuid4()),
            hostname="pc-01.example.local",
            ip_address="10.40.1.20",
            os="windows_11",
        )
        self.assertEqual(payload.hostname, "pc-01.example.local")
        self.assertEqual(payload.ip_address, "10.40.1.20")

    def test_heartbeat_contains_hardware_and_complete_software_snapshot(self):
        payload = AgentHeartbeatRequest(
            machine_id=str(uuid.uuid4()),
            hostname="pc-01",
            os="windows_11",
            status="online",
            ssh_login=r"rtf\s.u.mirzagitov",
            ssh_port=5022,
            hardware={"manufacturer": "Dell", "model": "OptiPlex", "fingerprint": "abc123"},
            software=[AgentSoftware(name="7-Zip", version="24.0", source="registry")],
        )
        self.assertEqual(payload.software[0].name, "7-Zip")
        self.assertEqual(payload.hardware.fingerprint, "abc123")
        self.assertEqual(payload.ssh_login, r"rtf\s.u.mirzagitov")
        self.assertEqual(payload.ssh_port, 5022)

    def test_heartbeat_scrubs_control_chars_rejected_by_postgres(self):
        # Vendor DisplayName values in the registry sometimes contain NUL, which
        # PostgreSQL text columns reject — failing the whole heartbeat.
        software = AgentSoftware(name="Foo\x00 Bar\x07", version="1.0\x00", publisher="\x00", source="registry")
        self.assertEqual(software.name, "Foo Bar")
        self.assertEqual(software.version, "1.0")
        self.assertIsNone(software.publisher)
        self.assertEqual(AgentSoftware(name="\x00\x01").name, "(unknown)")

    def test_alert_requires_message(self):
        with self.assertRaises(ValidationError):
            AgentAlertRequest(machine_id=str(uuid.uuid4()), alert_type="hardware_changed", message="")

    def test_agent_tokens_are_verifiable_only_by_hash(self):
        token = issue_agent_token()
        digest = hash_agent_token(token)
        self.assertTrue(verify_agent_token(token, digest))
        self.assertFalse(verify_agent_token("wrong", digest))

    def test_enrollment_token_can_be_reused_until_revoked(self):
        token = issue_agent_token()
        digest = hash_agent_token(token)
        self.assertTrue(verify_agent_token(token, digest))
        self.assertTrue(verify_agent_token(token, digest))

    def test_enrollment_tokens_have_no_group_binding(self):
        from schemas.agent import AgentEnrollmentTokenCreate

        payload = AgentEnrollmentTokenCreate(name="all-agents", expires_at=None)
        self.assertFalse(hasattr(payload, "group_id"))

    def test_registration_response_contains_ssh_public_key(self):
        from schemas.agent import AgentRegisterResponse

        self.assertIn("ssh_public_key", AgentRegisterResponse.model_fields)

    def test_registration_accepts_the_actual_ssh_login(self):
        payload = AgentRegisterRequest(
            enrollment_token="enrollment-secret-12345",
            machine_id=str(uuid.uuid4()),
            hostname="pc-01.example.local",
            os="windows_11",
            ssh_login=r"rtf\s.u.mirzagitov",
            ssh_port=5022,
        )
        self.assertEqual(payload.ssh_login, r"rtf\s.u.mirzagitov")
        self.assertEqual(payload.ssh_port, 5022)


class MachineIdCloneGuardTests(unittest.TestCase):
    """PCs deployed from one image without sysprep can share the agent machine-id."""

    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)

    def test_other_pc_with_the_id_of_a_reporting_host_is_a_clone(self):
        self.assertTrue(is_machine_id_clone("SU5-E302-01", self.now - timedelta(minutes=3), "SU5-E302-02", self.now))

    def test_same_pc_re_registering_is_allowed(self):
        # NetBIOS-имя и FQDN, разный регистр — это тот же ПК.
        self.assertFalse(is_machine_id_clone("su5-e302-01.at.urfu.ru", self.now - timedelta(minutes=3), "SU5-E302-01", self.now))

    def test_host_that_went_quiet_can_be_taken_over(self):
        last_seen = self.now - CLONE_GUARD_WINDOW - timedelta(seconds=1)
        self.assertFalse(is_machine_id_clone("SU5-E302-01", last_seen, "SU5-E302-02", self.now))

    def test_host_without_heartbeat_or_names_is_not_blocked(self):
        self.assertFalse(is_machine_id_clone("SU5-E302-01", None, "SU5-E302-02", self.now))
        self.assertFalse(is_machine_id_clone(None, self.now, "SU5-E302-02", self.now))
        self.assertFalse(is_machine_id_clone("SU5-E302-01", self.now, None, self.now))


if __name__ == "__main__":
    unittest.main()
