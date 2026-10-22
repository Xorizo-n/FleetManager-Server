import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from services import installer_builder
from services.agent_version import INSTALLER_FILENAME, VERSION_SIDECAR
from services.installer_builder import MASK_LOG_PS1, build_installer_exe, render_nsi

TOKEN = "AbC-123_xyz" * 4
SERVER = "http://10.40.240.154:8080"


def _render(**overrides):
    values = dict(
        server_url=SERVER,
        enrollment_token=TOKEN,
        setup_exe="/mnt/soft-share/FleetManagerAgent-Setup.exe",
        mask_ps1="/tmp/x/mask-log.ps1",
        output="/tmp/x/installer.exe",
        version="2026.10.20.21",
    )
    values.update(overrides)
    return render_nsi(**values)


class RenderNsiTests(unittest.TestCase):
    def test_runs_inno_installer_silently_with_server_and_token(self):
        nsi = _render()
        self.assertIn('File "/oname=$PLUGINSDIR\\FleetManagerAgent-Setup.exe" "/mnt/soft-share/FleetManagerAgent-Setup.exe"', nsi)
        exec_line = next(line for line in nsi.splitlines() if "ExecWait" in line)
        for arg in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", f"/ServerUrl={SERVER}", f"/EnrollmentToken={TOKEN}"):
            self.assertIn(arg, exec_line)
        self.assertIn('/LOG="$PLUGINSDIR\\setup.log"', exec_line)

    def test_token_appears_only_on_the_installer_command_line(self):
        lines = [line for line in _render().splitlines() if TOKEN in line]
        self.assertEqual(len(lines), 1)
        self.assertIn("ExecWait", lines[0])

    def test_nothing_is_installed_from_the_old_agent_dist(self):
        nsi = _render()
        for stale in ("agent-dist", "install.ps1", "bootstrap.ps1", "OpenSSH-Win64.msi", "InstallDir", "Program Files"):
            self.assertNotIn(stale, nsi)

    def test_temporary_files_live_in_pluginsdir_and_are_removed(self):
        nsi = _render()
        self.assertIn("InitPluginsDir", nsi)
        self.assertIn('Delete "$PLUGINSDIR\\setup.log"', nsi)
        self.assertIn('Delete "$PLUGINSDIR\\FleetManagerAgent-Setup.exe"', nsi)
        # Копия журнала пишется только через маскирующий скрипт.
        self.assertIn('mask-log.ps1" "$PLUGINSDIR\\setup.log" "$APPDATA\\FleetManagerAgent\\logs\\setup.log"', nsi)
        self.assertIn("SetShellVarContext all", nsi)

    def test_failure_shows_exit_code_and_log_paths(self):
        nsi = _render()
        box = next(line for line in nsi.splitlines() if "MessageBox" in line)
        self.assertIn("код $0", box)
        self.assertIn("$APPDATA\\FleetManagerAgent\\logs\\setup.log", box)
        self.assertIn("$APPDATA\\FleetManagerAgent\\logs\\install.log", box)
        self.assertIn("/SD IDOK", box)  # тихий запуск обёртки (/S) не зависает на окне
        self.assertIn("SetErrorLevel $0", nsi)
        for code in range(1, 9):
            self.assertIn(f"$0 == {code}\n", nsi)

    def test_version_goes_to_the_window_title(self):
        self.assertIn('Name "FleetManager Agent 2026.10.20.21"', _render())
        self.assertIn('Name "FleetManager Agent"', _render(version=None))

    def test_rejects_values_unsafe_for_nsis_or_the_command_line(self):
        for token in ('abc"def', "abc def", "abc$def", ""):
            with self.subTest(token=token), self.assertRaises(ValueError):
                _render(enrollment_token=token)
        for url in ("ftp://host", 'http://host" /DIR=x', "http://host/$x", "http://host path"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                _render(server_url=url)

    def test_https_and_ipv6_urls_are_accepted(self):
        _render(server_url="https://fleet.at.urfu.ru")
        _render(server_url="http://[fe80::1]:8080/")


class MaskLogTests(unittest.TestCase):
    def _mask(self, text):
        # Тот же шаблон, что в mask-log.ps1 (.NET и Python понимают его одинаково).
        pattern = re.search(r"Replace\(\$text, '(.+?)', '\$1\*\*\*'\)", MASK_LOG_PS1).group(1)
        return re.sub(pattern, r"\1***", text)

    def test_masks_token_in_inno_command_line(self):
        line = f'Setup command line: /SL5="$1,2,3" /VERYSILENT /LOG="C:\\T\\setup.log" /ServerUrl={SERVER} /EnrollmentToken={TOKEN}\r\nnext'
        masked = self._mask(line)
        self.assertNotIn(TOKEN, masked)
        self.assertIn("/EnrollmentToken=***\r\nnext", masked)
        self.assertIn(f"/ServerUrl={SERVER}", masked)

    def test_masks_quoted_token(self):
        self.assertEqual(self._mask(f'/enrollmenttoken="{TOKEN}" x'), "/enrollmenttoken=*** x")


class BuildInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch("services.agent_version.settings.soft_share_dir", self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.setup_exe = os.path.join(self.tmp.name, INSTALLER_FILENAME)

    def _add_installer(self, version="v2026.10.20.21"):
        with open(self.setup_exe, "wb") as f:
            f.write(b"MZ" + os.urandom(4096))
        with open(os.path.join(self.tmp.name, VERSION_SIDECAR), "w", encoding="utf-8") as f:
            f.write(version)

    def test_missing_inno_installer_is_reported(self):
        with self.assertRaisesRegex(RuntimeError, "не синхронизирован"):
            build_installer_exe(SERVER, TOKEN)

    def test_makensis_gets_rendered_script(self):
        self._add_installer()
        seen = {}

        def fake_run(cmd, **kwargs):
            nsi_path = cmd[-1]
            with open(nsi_path, encoding="utf-8-sig") as f:
                seen["nsi"] = f.read()
            with open(os.path.join(os.path.dirname(nsi_path), "mask-log.ps1"), encoding="ascii") as f:
                seen["ps1"] = f.read()
            with open(os.path.join(os.path.dirname(nsi_path), "installer.exe"), "wb") as f:
                f.write(b"built")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("services.installer_builder.subprocess.run", side_effect=fake_run) as run:
            self.assertEqual(build_installer_exe(SERVER, TOKEN), b"built")

        self.assertEqual(run.call_args.args[0][:4], ["makensis", "-V2", "-INPUTCHARSET", "UTF8"])
        self.assertIn(f'"{self.setup_exe}"', seen["nsi"])
        self.assertIn("FleetManager Agent 2026.10.20.21", seen["nsi"])
        self.assertNotIn(TOKEN, seen["ps1"])

    def test_makensis_error_does_not_leak_token(self):
        self._add_installer()
        failed = subprocess.CompletedProcess(["makensis"], 1, f"line 30: ExecWait ... /EnrollmentToken={TOKEN}", "")
        with patch("services.installer_builder.subprocess.run", return_value=failed):
            with self.assertRaises(RuntimeError) as ctx:
                build_installer_exe(SERVER, TOKEN)
        self.assertNotIn(TOKEN, str(ctx.exception))

    @unittest.skipUnless(shutil.which("makensis"), "makensis is not installed")
    def test_real_makensis_compiles_wrapper(self):
        self._add_installer()
        exe = build_installer_exe(SERVER, TOKEN)
        self.assertTrue(exe.startswith(b"MZ"))
        self.assertGreater(len(exe), 4096)


if __name__ == "__main__":
    unittest.main()
