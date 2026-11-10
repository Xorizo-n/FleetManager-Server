import unittest

from services.agent_ssh import generate_agent_keypair, preferred_ssh_login


class AgentSshTests(unittest.TestCase):
    def test_generated_keypair_has_openssh_public_and_private_parts(self):
        private_key, public_key = generate_agent_keypair()
        self.assertIn("BEGIN RSA PRIVATE KEY", private_key)
        self.assertTrue(public_key.startswith("ssh-rsa "))


class PreferredSshLoginTests(unittest.TestCase):
    SERVICE = r"AT\svc-fleet"

    def test_same_domain_user_is_replaced_by_service_login(self):
        self.assertEqual(preferred_ssh_login(r"AT\ivan.ivanov", self.SERVICE), self.SERVICE)
        self.assertEqual(preferred_ssh_login(r"at\Petr.Petrov", self.SERVICE), self.SERVICE)

    def test_other_domain_and_local_logins_are_kept(self):
        self.assertEqual(preferred_ssh_login(r"RTF\svc-other", self.SERVICE), r"RTF\svc-other")
        self.assertEqual(preferred_ssh_login("admin", self.SERVICE), "admin")
        self.assertIsNone(preferred_ssh_login(None, self.SERVICE))

    def test_without_service_login_reported_is_kept(self):
        self.assertEqual(preferred_ssh_login(r"AT\ivan.ivanov", ""), r"AT\ivan.ivanov")


if __name__ == "__main__":
    unittest.main()
