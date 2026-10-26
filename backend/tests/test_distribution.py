import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from config import settings
from services import distribution

SECRET = "0" * 64
URL = "http://10.152.240.10:8088"


class _Share(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.share = os.path.join(self.tmp.name, "share")
        os.makedirs(self.share)
        self.data = os.path.join(self.tmp.name, "data")
        os.makedirs(self.data)
        for name, value in {"soft_share_dir": self.share, "dist_url": URL, "dist_secret": SECRET,
                            "dist_rsync_target": "fleetdist@10.152.240.10",
                            "dist_manifest_path": os.path.join(self.data, "dist-manifest.json"),
                            "dist_state_path": os.path.join(self.data, "dist-state.json")}.items():
            patcher = mock.patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def put(self, rel: str, content: bytes = b"installer") -> str:
        path = os.path.join(self.share, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return path


class SignTests(unittest.TestCase):
    def test_link_matches_nginx_secure_link_md5(self):
        # nginx: secure_link_md5 "$secure_link_expires$uri <secret>"; $uri is the decoded path
        with mock.patch.object(settings, "dist_url", URL), mock.patch.object(settings, "dist_secret", SECRET):
            link = distribution.sign_path("Сборка/app 1+2.exe", ttl_seconds=60, now=1_000_000)
        expected = base64.urlsafe_b64encode(
            hashlib.md5(f"1000060/Сборка/app 1+2.exe {SECRET}".encode()).digest()).rstrip(b"=").decode()
        self.assertTrue(link.startswith(URL + "/%D0%A1%D0%B1%D0%BE%D1%80%D0%BA%D0%B0/app%201%2B2.exe?"))
        self.assertTrue(link.endswith(f"?md5={expected}&expires=1000060"))


class ManifestTests(_Share):
    def test_service_files_are_not_distributed(self):
        for rel in (".upload-tmp/x.exe", "lost+found/x", "app.exe.part", "dir/.hidden", ".rsync-partial/a"):
            self.assertTrue(distribution._excluded(rel), rel)
        self.assertFalse(distribution._excluded("wallpapers/abc.jpg"))

    def test_sync_records_files_that_did_not_change_during_transfer(self):
        stable = self.put("7z2409-x64.exe", b"stable")
        self.put("sub/tool.msi", b"tool")
        self.put("upload.exe.part", b"partial")
        changing = self.put("busy.iso", b"v1")

        def rsync(command, **_):
            with open(changing, "ab") as f:  # загрузка дописывает файл во время передачи
                f.write(b"more")
            return subprocess.CompletedProcess(command, 0, "", "")

        with mock.patch.object(distribution.subprocess, "run", side_effect=rsync), \
             mock.patch.object(distribution, "check_health", return_value=True):
            result = distribution.sync()

        files = distribution.load_manifest()
        self.assertEqual(sorted(files), ["7z2409-x64.exe", "sub/tool.msi"])
        self.assertEqual(files["7z2409-x64.exe"][2], hashlib.sha256(b"stable").hexdigest())
        self.assertEqual(result["pending"], 1)
        status = distribution.status()
        self.assertTrue(status["healthy"])
        self.assertIsNone(status["error"])
        self.assertFalse(status["running"])
        self.assertEqual(distribution.link_for(stable)[1], hashlib.sha256(b"stable").hexdigest())

    def test_file_replaced_after_sync_is_not_offered(self):
        path = self.put("app.exe", b"old")
        with mock.patch.object(distribution.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")), \
             mock.patch.object(distribution, "check_health", return_value=True):
            distribution.sync()
        self.assertIsNotNone(distribution.link_for(path))
        self.put("app.exe", b"new and longer")
        self.assertIsNone(distribution.link_for(path))

    def test_unchanged_files_are_not_hashed_again(self):
        self.put("big.ova", b"x" * 10)
        ok = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(distribution.subprocess, "run", return_value=ok), \
             mock.patch.object(distribution, "check_health", return_value=True):
            distribution.sync()
            with mock.patch.object(distribution, "_sha256") as sha:
                distribution.sync()
        sha.assert_not_called()

    def test_failed_rsync_keeps_the_previous_manifest_and_reports_the_error(self):
        path = self.put("app.exe")
        ok = subprocess.CompletedProcess([], 0, "", "")
        failed = subprocess.CompletedProcess([], 255, "", "ssh: connect to host 10.152.240.10 port 22: Connection refused")
        with mock.patch.object(distribution, "check_health", return_value=False):
            with mock.patch.object(distribution.subprocess, "run", return_value=ok):
                distribution.sync()
            with mock.patch.object(distribution.subprocess, "run", return_value=failed):
                result = distribution.sync()
        self.assertIn("255", result["error"])
        self.assertIn("Connection refused", distribution.status()["error"])
        self.assertIsNotNone(distribution.link_for(path))

    def test_files_outside_the_share_get_no_link(self):
        outside = os.path.join(self.tmp.name, "secret.txt")
        with open(outside, "w") as f:
            f.write("x")
        self.assertIsNone(distribution.link_for(outside))

    def test_disabled_without_url(self):
        path = self.put("app.exe")
        with mock.patch.object(settings, "dist_url", ""):
            self.assertIsNone(distribution.link_for(path))
            self.assertIn("skipped", distribution.sync())

    def test_rsync_mirrors_with_deletion_and_skips_service_files(self):
        command = distribution.rsync_command(self.share)
        self.assertIn("--delete", command)
        self.assertIn("--exclude=/.upload-tmp/", command)
        self.assertIn("--exclude=*.part", command)
        self.assertIn("StrictHostKeyChecking=yes", command[command.index("-e") + 1])
        self.assertEqual(command[-2:], [self.share + "/", "fleetdist@10.152.240.10:"])


class FetchPluginTests(_Share):
    """Плагин работает в ansible-playbook и читает настройки из окружения — те же, что config.py."""

    def setUp(self):
        super().setUp()
        try:
            import ansible  # noqa: F401
        except ImportError:
            self.skipTest("ansible не установлен")
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ansible_plugins", "action"))
        self.addCleanup(sys.path.pop, 0)
        import fm_fetch

        self.plugin = fm_fetch
        for name, value in {"SHARE": self.share, "MANIFEST": settings.dist_manifest_path}.items():
            patcher = mock.patch.object(fm_fetch, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"DIST_URL": URL, "DIST_SECRET": SECRET})
        env.start()
        self.addCleanup(env.stop)

    def _manifest(self, rel, path, sha="ab" * 32):
        stat = os.stat(path)
        with open(settings.dist_manifest_path, "w") as f:
            json.dump({"files": {rel: [stat.st_size, stat.st_mtime_ns, sha]}}, f)

    def test_file_on_the_distribution_point_is_downloaded(self):
        path = self.put("7z.exe")
        self._manifest("7z.exe", path)
        self.assertEqual(self.plugin.distribution_entry(path), ("7z.exe", "ab" * 32))

    def test_signature_is_the_same_as_the_server_one(self):
        with mock.patch.object(self.plugin.time, "time", return_value=1_000_000), \
             mock.patch.object(self.plugin, "TTL", 60):
            self.assertEqual(self.plugin._sign("a b.exe"), distribution.sign_path("a b.exe", 60, now=1_000_000))

    def test_anything_else_falls_back_to_win_copy(self):
        path = self.put("7z.exe")
        self.assertIsNone(self.plugin.distribution_entry(path))  # нет в манифесте
        self._manifest("7z.exe", path)
        self.put("7z.exe", b"replaced after sync")
        self.assertIsNone(self.plugin.distribution_entry(path))
        self.assertIsNone(self.plugin.distribution_entry("files/relative.exe"))
        with mock.patch.dict(os.environ, {"DIST_URL": ""}):
            self.assertIsNone(self.plugin.distribution_entry(path))


if __name__ == "__main__":
    unittest.main()
