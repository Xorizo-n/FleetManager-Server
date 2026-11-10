import hashlib
import io
import json
import tarfile
import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from updater.release import manifest, unpack, version
from updater.runner import Updater, atomic


def valid_manifest():
    return {"format": 1, "version": "v1.0.0", "commit": "a" * 40, "schema_revision": "0039_host_restart",
            "bundle_sha256": "b" * 64, "images": {name: f"ghcr.io/xorizo-n/fleet-manager-{name}@sha256:" + "c" * 64
                                                  for name in ("backend", "frontend")}}


class ReleaseTests(unittest.TestCase):
    def test_numeric_stable_versions(self):
        self.assertGreater(version("v1.0.10"), version("v1.0.9"))
        for value in ("main", "v1.0.0-rc1", "v01.0.0", "../../x", "v1.0.0\n", None):
            with self.assertRaises(ValueError):
                version(value)

    def test_manifest_rejects_unpinned_or_foreign_images(self):
        manifest(valid_manifest(), "v1.0.0")
        for image in ("ubuntu:latest", "ghcr.io/xorizo-n/fleet-manager-backend:latest", "https://example.com/script"):
            value = valid_manifest()
            value["images"]["backend"] = image
            with self.assertRaises(ValueError):
                manifest(value, "v1.0.0")

    def test_manifest_rejects_wrong_version_schema_and_hash(self):
        for key, value in (("version", "v2.0.0"), ("format", 2), ("schema_revision", "../script"), ("bundle_sha256", "xyz")):
            data = valid_manifest(); data[key] = value
            with self.assertRaises(ValueError):
                manifest(data, "v1.0.0")

    def archive(self, name="compose.json", link=False):
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w:gz") as archive:
            member = tarfile.TarInfo(name)
            if link:
                member.type, member.linkname = tarfile.SYMTYPE, "/etc/passwd"
                archive.addfile(member)
            else:
                member.size = 2
                archive.addfile(member, io.BytesIO(b"{}"))
        return out.getvalue()

    def test_unpack_checks_hash_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self.archive()
            unpack(data, tmp, hashlib.sha256(data).hexdigest())
            self.assertEqual(Path(tmp, "compose.json").read_text(), "{}")
            with self.assertRaises(ValueError):
                unpack(data, tmp, "0" * 64)
            for name, link in (("../outside", False), ("/etc/passwd", False), ("ansible/link", True), (".env", False), ("ansible\\..\\x", False)):
                data = self.archive(name, link)
                with self.assertRaises(ValueError):
                    unpack(data, tmp, hashlib.sha256(data).hexdigest())

    @patch("updater.release.get")
    def test_release_accepts_only_complete_stable_assets(self, get):
        from updater.release import release
        for row in ({"tag_name": "v1.0.0", "assets": []}, {"tag_name": "v1.0.0", "prerelease": True}, {"tag_name": "main"}):
            get.return_value = json.dumps(row).encode()
            with self.assertRaises(ValueError):
                release()


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.updater = Updater(self.root, self.root / "state", self.root / "run", wait_seconds=0)

    def operation(self, **extra):
        self.updater.data["operation"] = {"id": "test", "version": "v1.0.0", "status": "preparing", "events": [], **extra}

    def test_network_error_preserves_last_known_release(self):
        self.updater.data["available"] = valid_manifest()
        with patch("updater.runner.release", side_effect=TimeoutError("timeout")):
            status = self.updater.check()
        self.assertEqual(status["available"]["version"], "v1.0.0")
        self.assertIn("timeout", status["check_error"])
        self.assertFalse(self.updater.lock.locked())

    def test_no_published_release_is_not_a_network_error(self):
        from urllib.error import HTTPError
        with patch("updater.runner.release", side_effect=HTTPError("url", 404, "not found", {}, None)):
            status = self.updater.check()
        self.assertIsNone(status["available"])
        self.assertIsNone(status["check_error"])

    def test_only_one_operation_and_no_downgrade(self):
        self.updater.lock.acquire()
        with self.assertRaises(ValueError): self.updater.start("v1.0.0", "admin")
        with self.assertRaises(ValueError): self.updater.check()
        self.updater.lock.release()
        self.updater.data["current"]["version"] = "v2.0.0"
        with self.assertRaises(ValueError): self.updater.start("v1.0.0", "admin")
        self.assertFalse(self.updater.lock.locked())

    def test_worker_failure_before_changes_keeps_platform_running(self):
        self.operation()
        self.updater.lock.acquire()
        with patch.object(self.updater, "install", side_effect=RuntimeError("download failed")):
            self.updater.worker()
        self.assertEqual(self.updater.data["operation"]["status"], "failed")
        self.assertFalse(self.updater.runtime.joinpath("maintenance").exists())

    def test_migration_failure_keeps_maintenance_and_does_not_rollback_images(self):
        self.operation(migration_started=True, backup_complete=True, previous_compose="old")
        self.updater.lock.acquire()
        with patch.object(self.updater, "install", side_effect=RuntimeError("migration failed")), patch.object(self.updater, "resume") as resume:
            self.updater.worker()
        resume.assert_not_called()
        self.assertEqual(self.updater.data["operation"]["status"], "recovery_required")
        self.assertTrue(self.updater.runtime.joinpath("maintenance").exists())

    def test_same_schema_failure_can_return_to_previous_images(self):
        self.operation(migration_started=True, schema_unchanged=True, previous_compose="old", quiesced=True)
        self.updater.lock.acquire()
        with patch.object(self.updater, "install", side_effect=RuntimeError("health failed")), patch.object(self.updater, "resume") as resume:
            self.updater.worker()
        resume.assert_called_once_with(Path("old"))
        self.assertEqual(self.updater.data["operation"]["status"], "failed")

    def test_wait_timeout_never_stops_worker(self):
        self.operation()
        with patch.object(self.updater, "dc") as dc, patch.object(self.updater, "inspect_tasks", return_value=True):
            with self.assertRaises(RuntimeError): self.updater.quiesce()
        stops = [c.args for c in dc.call_args_list if c.args[0] == "stop"]
        self.assertEqual(stops, [("stop", "celery-beat")])

    def test_missing_inspect_reply_fails_closed(self):
        with patch.object(self.updater, "dc", return_value=b"[null, {}, {}]"):
            with self.assertRaises(RuntimeError): self.updater.inspect_tasks()

    def test_reboot_after_migration_requires_explicit_recovery(self):
        self.operation(migration_started=True, previous_compose="old", backup_complete=True)
        self.updater.save()
        restarted = Updater(self.root, self.root / "state", self.root / "run")
        self.assertEqual(restarted.data["operation"]["status"], "recovery_required")
        self.assertTrue(restarted.runtime.joinpath("maintenance").exists())

    def test_reboot_during_download_does_not_block_platform(self):
        self.operation()
        self.updater.save()
        restarted = Updater(self.root, self.root / "state", self.root / "run")
        self.assertEqual(restarted.data["operation"]["status"], "failed")
        self.assertFalse(restarted.runtime.joinpath("maintenance").exists())

    def test_restore_requires_ready_copy_after_migration(self):
        self.operation(status="recovery_required", migration_started=True, previous_compose="old")
        with self.assertRaises(ValueError): self.updater.start(None, "admin", restore=True)

    def test_restore_failure_retains_maintenance(self):
        self.operation()
        self.updater.lock.acquire()
        with patch.object(self.updater, "restore", side_effect=RuntimeError("restore failed")):
            self.updater.worker(restore=True)
        self.assertEqual(self.updater.data["operation"]["status"], "recovery_required")

    def test_damaged_backup_is_rejected_before_any_database_command(self):
        directory = self.root / "backup"; directory.mkdir()
        self.operation(previous_compose="old", backup=str(directory), migration_started=True,
                       backup_hashes={"database.dump": "0" * 64})
        with patch.object(self.updater, "dc") as dc, patch.object(self.updater, "cmd") as cmd:
            with self.assertRaisesRegex(RuntimeError, "повреждена"):
                self.updater.restore()
        dc.assert_not_called(); cmd.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "Unix socket service runs on Linux")
    def test_socket_service_status_and_invalid_operation(self):
        import threading
        from updater.service import Server, UnixConnection, handler
        path = str(self.root / "socket")
        with Server(path, handler(self.updater)) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                connection = UnixConnection(path)
                connection.request("GET", "/status")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["current"]["version"], "unversioned")
                connection.close()
                connection = UnixConnection(path)
                connection.request("POST", "/arbitrary-command", "{}")
                response = connection.getresponse()
                self.assertEqual(response.status, 409)
                response.read(); connection.close()
            finally:
                server.shutdown()


if __name__ == "__main__":
    unittest.main()
