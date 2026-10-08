import unittest
from pathlib import Path


class ContainerDependencyTests(unittest.TestCase):
    def test_backend_image_installs_sshpass_for_password_credentials(self):
        dockerfile = Path(__file__).parents[1] / "Dockerfile"
        self.assertIn("sshpass", dockerfile.read_text(encoding="utf-8"))

    def test_celery_worker_can_write_agent_installer_to_soft_share(self):
        # sync-agent-installer (celery beat) runs in the worker and writes the
        # installer into the share, so the share must not be mounted read-only there.
        import yaml

        compose = yaml.safe_load((Path(__file__).parents[2] / "docker-compose.yml").read_text(encoding="utf-8"))
        share_mounts = [v for v in compose["services"]["celery"]["volumes"] if ":/mnt/soft-share" in v]
        self.assertEqual(len(share_mounts), 1)
        self.assertFalse(share_mounts[0].endswith(":ro"))


if __name__ == "__main__":
    unittest.main()
