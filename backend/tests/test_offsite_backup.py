import unittest
from unittest import mock

from pydantic import ValidationError

from config import settings
from services import offsite_backup as ob

TARGET = ob.Target(host="10.152.240.10", port=22, user="backupuser", path="/srv/backup/fleet-manager",
                   password="sftp-secret", repo_password="repo-secret-123", host_key="ssh-ed25519 AAAAC3Nza")


class ResticHelpersTests(unittest.TestCase):
    def test_repository_url(self):
        self.assertEqual(TARGET.repository, "sftp:backupuser@10.152.240.10:/srv/backup/fleet-manager")

    def test_errors_are_explained(self):
        self.assertIn("ещё не создано", ob.explain("Fatal: unable to open config file: ... Is there a repository at the following location?"))
        self.assertIn("пароль шифрования", ob.explain("Fatal: wrong password or no key found"))
        self.assertIn("логин или пароль", ob.explain("backupuser@10.152.240.10: Permission denied (password)."))
        self.assertIn("изменился", ob.explain("Host key verification failed."))
        self.assertIn("занято", ob.explain("unable to create lock in backend: repository is already locked by PID 7"))
        self.assertEqual(ob.explain("something odd\nlast line"), "last line")

    def test_pg_env_from_database_url(self):
        with mock.patch.object(settings, "database_url", "postgresql+psycopg://fleet:p%40ss@postgres:5432/fleet_manager"):
            env = ob.pg_env()
            self.assertEqual(env, {"PGHOST": "postgres", "PGPORT": "5432", "PGUSER": "fleet", "PGPASSWORD": "p@ss", "PGDATABASE": "fleet_manager"})
            self.assertEqual(ob.pg_env("postgres")["PGDATABASE"], "postgres")

    def test_env_value(self):
        text = "JWT_SECRET_KEY=x\n# comment\nCREDENTIAL_ENCRYPTION_KEY='abc='\n"
        self.assertEqual(ob._env_value(text, "CREDENTIAL_ENCRYPTION_KEY"), "abc=")
        self.assertIsNone(ob._env_value(text, "MISSING"))

    def test_summary_is_the_last_summary_line(self):
        out = '{"message_type":"status","percent_done":0.5}\n{"message_type":"summary","snapshot_id":"abc","data_added":42}\n'
        self.assertEqual(ob._summary(out)["snapshot_id"], "abc")
        with self.assertRaises(ob.BackupError):
            ob._summary('{"message_type":"status"}')

    def test_password_never_in_command_line(self):
        with ob._restic_env(TARGET) as (env, options):
            command = " ".join(options)
            self.assertNotIn("sftp-secret", command)
            self.assertNotIn("repo-secret-123", command)
            self.assertEqual(env["SSHPASS"], "sftp-secret")
            self.assertEqual(env["RESTIC_PASSWORD"], "repo-secret-123")
            self.assertIn("StrictHostKeyChecking=yes", command)
            self.assertIn("PubkeyAuthentication=no", command)
            # restic режет значение sftp.command по запятым
            self.assertNotIn(",", options[1])

    def test_unpinned_host_key_refuses(self):
        with self.assertRaisesRegex(ob.BackupError, "не закреплён"):
            with ob._restic_env(ob.Target(**{**TARGET.__dict__, "host_key": None})):
                pass

    def test_repository_state(self):
        missing = mock.Mock(returncode=1, stderr="Is there a repository at the following location?")
        with mock.patch.object(ob, "restic", return_value=missing):
            self.assertEqual(ob.repository_state(TARGET), "missing")
        with mock.patch.object(ob, "restic", return_value=mock.Mock(returncode=0, stderr="")):
            self.assertEqual(ob.repository_state(TARGET), "exists")
        with mock.patch.object(ob, "restic", return_value=mock.Mock(returncode=1, stderr="wrong password or no key found")):
            with self.assertRaisesRegex(ob.BackupError, "пароль"):
                ob.repository_state(TARGET)

    def test_db_backup_requires_env_file(self):
        with mock.patch.object(settings, "offsite_config_dir", "/nonexistent-fleet-config"):
            with self.assertRaisesRegex(ob.BackupError, ".env"):
                ob.backup_db(TARGET)


class BackupSettingsSchemaTests(unittest.TestCase):
    def payload(self, **kw):
        from routers.backup import BackupSettingsIn

        base = dict(enabled=True, sftp_host="10.152.240.10", sftp_user="backupuser", sftp_path="/srv/backup/fleet-manager/")
        return BackupSettingsIn(**{**base, **kw})

    def test_path_trimmed_and_absolute(self):
        self.assertEqual(self.payload().sftp_path, "/srv/backup/fleet-manager")
        with self.assertRaises(ValidationError):
            self.payload(sftp_path="backup")

    def test_shell_characters_rejected(self):
        for field, value in (("sftp_host", "h;rm"), ("sftp_user", "a b"), ("sftp_path", "/srv/$(x)")):
            with self.assertRaises(ValidationError, msg=field):
                self.payload(**{field: value})

    def test_schedule_is_registered(self):
        from celery_app import celery_app

        schedule = celery_app.conf.beat_schedule
        self.assertEqual(schedule["offsite-backup-db"]["args"], ("db",))
        self.assertEqual(schedule["offsite-backup-share"]["args"], ("share",))
        self.assertEqual(schedule["offsite-backup-check"]["args"], ("check",))


if __name__ == "__main__":
    unittest.main()
