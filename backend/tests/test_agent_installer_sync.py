import os
import tempfile
import unittest
from unittest.mock import patch

from services.agent_installer_sync import INSTALLER_FILENAME, VERSION_SIDECAR, sync_agent_installer


class AgentInstallerSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = patch("services.agent_installer_sync.settings.soft_share_dir", self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def _release(self, tag="v2026.01.01.1", with_asset=True):
        assets = [{"name": INSTALLER_FILENAME, "browser_download_url": "https://example.invalid/x.exe"}] if with_asset else []
        return {"tag_name": tag, "assets": assets}

    def test_downloads_when_no_local_version(self):
        with patch("services.agent_installer_sync._latest_release", return_value=self._release()), \
             patch("services.agent_installer_sync._download_asset") as download:
            result = sync_agent_installer()

        self.assertTrue(result["updated"])
        self.assertEqual(result["version"], "v2026.01.01.1")
        download.assert_called_once()
        with open(os.path.join(self.tmp.name, VERSION_SIDECAR), encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), "v2026.01.01.1")

    def test_skips_download_when_already_current(self):
        with open(os.path.join(self.tmp.name, VERSION_SIDECAR), "w", encoding="utf-8") as f:
            f.write("v2026.01.01.1")

        with patch("services.agent_installer_sync._latest_release", return_value=self._release()), \
             patch("services.agent_installer_sync._download_asset") as download:
            result = sync_agent_installer()

        self.assertFalse(result["updated"])
        download.assert_not_called()

    def test_reports_missing_asset(self):
        with patch("services.agent_installer_sync._latest_release", return_value=self._release(with_asset=False)), \
             patch("services.agent_installer_sync._download_asset") as download:
            result = sync_agent_installer()

        self.assertFalse(result["updated"])
        download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
