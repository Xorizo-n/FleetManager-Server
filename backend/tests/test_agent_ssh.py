import unittest

from services.agent_ssh import generate_agent_keypair


class AgentSshTests(unittest.TestCase):
    def test_generated_keypair_has_openssh_public_and_private_parts(self):
        private_key, public_key = generate_agent_keypair()
        self.assertIn("BEGIN RSA PRIVATE KEY", private_key)
        self.assertTrue(public_key.startswith("ssh-rsa "))


if __name__ == "__main__":
    unittest.main()
