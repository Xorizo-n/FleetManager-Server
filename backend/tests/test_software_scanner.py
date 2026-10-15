import base64
import unittest

from services.software_scanner import REGISTRY_PACKAGES_CMD


def _decoded_script() -> str:
    return base64.b64decode(REGISTRY_PACKAGES_CMD.rsplit(" ", 1)[1]).decode("utf-16le")


class RegistryScanScriptTests(unittest.TestCase):
    def test_script_is_passed_as_encoded_powershell(self):
        self.assertTrue(REGISTRY_PACKAGES_CMD.startswith("powershell -NoProfile -NonInteractive -EncodedCommand "))

    def test_uninstall_entries_are_read_value_by_value(self):
        # NetBeans writes NoModify as an 8-byte REG_DWORD; Get-ItemProperty over
        # Uninstall\* then throws InvalidCastException and SU5-VM-SBX reported no
        # registry programs at all. A broken entry must only skip itself.
        script = _decoded_script()
        self.assertNotIn("Get-ItemProperty", script)
        self.assertIn("Get-ChildItem $keys", script)
        self.assertIn("GetValue('DisplayName')", script)
        self.assertIn("try {", script)

    def test_script_keeps_scope_and_filters(self):
        script = _decoded_script()
        for key in ("HKLM:\\Software\\Microsoft", "HKLM:\\Software\\WOW6432Node", "HKCU:\\Software\\Microsoft"):
            self.assertIn(key, script)
        self.assertIn("GetValue('SystemComponent') -ne 1", script)
        self.assertIn("Get-AppxPackage", script)
        self.assertIn("ConvertTo-Json -Compress", script)

    def test_command_fits_the_ssh_command_line(self):
        self.assertLess(len(REGISTRY_PACKAGES_CMD), 8000)


if __name__ == "__main__":
    unittest.main()
