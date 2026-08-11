import unittest

from routers.installers import ALLOWED_EXTENSIONS


class InstallerPolicyTests(unittest.TestCase):
    def test_zip_archives_are_allowed(self):
        self.assertIn(".zip", ALLOWED_EXTENSIONS)


if __name__ == "__main__":
    unittest.main()
