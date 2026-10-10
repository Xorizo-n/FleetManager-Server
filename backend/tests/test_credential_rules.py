import unittest
import uuid

from models.credential import Credential, CredentialType
from services.credential_rules import ssh_credential_error


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


if __name__ == "__main__":
    unittest.main()
