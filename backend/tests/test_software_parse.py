import unittest

from services.software_parse import parse_registry_packages
from services.software_parse import parse_get_package


class SoftwareParseTests(unittest.TestCase):
    def test_parse_get_package_ignores_windows_console_prefix(self):
        raw = '\x1b[2J\x1b[m\x1b[H[{"Name":"7-Zip","Version":"24.09"}]\x1b[H'
        self.assertEqual(parse_get_package(raw), [("7-Zip", "24.09")])

    def test_parse_registry_packages_joins_console_wrapped_json(self):
        raw = '[{"Name":"Microsoft Office","Vers\r\nion":"16.0"}]'
        self.assertEqual(parse_registry_packages(raw), [("Microsoft Office", "16.0")])

    def test_parse_registry_packages_reads_json_array(self):
        raw = '[{"Name":"7-Zip 24.09","Version":"24.09"},{"Name":"Visual Studio Code","Version":"1.95.3"}]'
        self.assertEqual(
            parse_registry_packages(raw),
            [("7-Zip 24.09", "24.09"), ("Visual Studio Code", "1.95.3")],
        )

    def test_parse_registry_packages_accepts_single_object(self):
        self.assertEqual(parse_registry_packages('{"Name":"App","Version":"1.0"}'), [("App", "1.0")])

    def test_parse_registry_packages_skips_entries_without_name(self):
        self.assertEqual(parse_registry_packages('[{"Name":"","Version":"1"},{"Version":"2"}]'), [])


if __name__ == "__main__":
    unittest.main()
