import unittest
import uuid

from pydantic import ValidationError

from schemas.agent import (
    AgentAlertRequest,
    AgentHeartbeatRequest,
    AgentRegisterRequest,
    AgentSoftware,
)
from services.agent_auth import hash_agent_token, issue_agent_token, verify_agent_token


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
            hardware={"manufacturer": "Dell", "model": "OptiPlex", "fingerprint": "abc123"},
            software=[AgentSoftware(name="7-Zip", version="24.0", source="registry")],
        )
        self.assertEqual(payload.software[0].name, "7-Zip")
        self.assertEqual(payload.hardware.fingerprint, "abc123")
        self.assertEqual(payload.ssh_login, r"rtf\s.u.mirzagitov")

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
        )
        self.assertEqual(payload.ssh_login, r"rtf\s.u.mirzagitov")


if __name__ == "__main__":
    unittest.main()
