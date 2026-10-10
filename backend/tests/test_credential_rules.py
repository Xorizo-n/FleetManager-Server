import unittest
import uuid

from models.credential import Credential, CredentialType
from services.credential_rules import host_credential_change_error, ssh_credential_error


def credential(type_=CredentialType.ssh_key, login="admin", agent=False):
    return Credential(id=uuid.uuid4(), name="c", type=type_, login=login, secret_encrypted="x", is_agent_managed=agent)


class SshCredentialTests(unittest.TestCase):
    def test_ssh_key_and_password_with_login_are_allowed(self):
        self.assertIsNone(ssh_credential_error(credential(CredentialType.ssh_key)))
        self.assertIsNone(ssh_credential_error(credential(CredentialType.password)))

    def test_token_is_rejected(self):
        self.assertIsNotNone(ssh_credential_error(credential(CredentialType.token)))

    def test_missing_login_is_rejected(self):
        self.assertIsNotNone(ssh_credential_error(credential(login=None)))
        self.assertIsNotNone(ssh_credential_error(credential(login="")))

    def test_agent_key_cannot_be_assigned_by_hand(self):
        self.assertIsNotNone(ssh_credential_error(credential(agent=True)))


class HostCredentialChangeTests(unittest.TestCase):
    def test_agent_key_cannot_be_replaced(self):
        agent_key = credential(agent=True)
        self.assertIsNotNone(host_credential_change_error(agent_key, credential().id))

    def test_agent_key_cannot_be_dropped_for_group_inheritance(self):
        self.assertIsNotNone(host_credential_change_error(credential(agent=True), None))

    def test_keeping_the_agent_key_is_fine(self):
        agent_key = credential(agent=True)
        self.assertIsNone(host_credential_change_error(agent_key, agent_key.id))

    def test_manual_credential_can_be_changed_or_inherited(self):
        manual = credential()
        self.assertIsNone(host_credential_change_error(manual, credential().id))
        self.assertIsNone(host_credential_change_error(manual, None))
        self.assertIsNone(host_credential_change_error(None, manual.id))


if __name__ == "__main__":
    unittest.main()
