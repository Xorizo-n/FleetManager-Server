import unittest
from pathlib import Path


class ContainerDependencyTests(unittest.TestCase):
    def test_backend_image_installs_sshpass_for_password_credentials(self):
        dockerfile = Path(__file__).parents[1] / "Dockerfile"
        self.assertIn("sshpass", dockerfile.read_text(encoding="utf-8"))

    def test_backend_image_installs_ansible_windows_collection(self):
        dockerfile = Path(__file__).parents[1] / "Dockerfile"
        requirements = Path(__file__).parents[1] / "ansible-collections.yml"
        self.assertIn("ansible-galaxy collection install", dockerfile.read_text(encoding="utf-8"))
        self.assertIn("ansible.windows", requirements.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
