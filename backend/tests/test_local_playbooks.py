import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from config import settings
from services import local_playbooks as lp

GOOD = """---
- name: Ping
  hosts: Win_Hosts
  gather_facts: false
  tasks:
    - name: Ping
      ansible.windows.win_ping:
"""


class LocalPlaybookTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        patcher = mock.patch.object(settings, "local_playbooks_dir", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.repo = SimpleNamespace(local_path=self.dir)

    def test_check_path_accepts_file_and_one_folder(self):
        self.assertEqual(lp.check_path("install_firefox.yml"), "install_firefox.yml")
        self.assertEqual(lp.check_path(" install\\firefox.yaml "), "install/firefox.yaml")

    def test_check_path_rejects_traversal_hidden_and_nested(self):
        for bad in ("../x.yml", ".hidden.yml", "a/b/c.yml", "x.txt", "/etc/x.yml", "имя.yml", "a b.yml", ""):
            with self.assertRaises(lp.PlaybookError, msg=bad):
                lp.check_path(bad)

    def test_resolve_stays_inside_the_repo(self):
        self.assertEqual(lp.resolve(self.repo, "install/x.yml"), (Path(self.dir) / "install/x.yml").resolve())
        for bad in ("../outside.yml", ".git/config"):
            with self.assertRaises(lp.PlaybookError, msg=bad):
                lp.resolve(self.repo, bad)

    def test_structure_errors_point_to_the_problem(self):
        with self.assertRaisesRegex(lp.PlaybookError, "строка 3"):
            lp.validate_structure("- name: x\n  hosts: all\n tasks: [\n")
        with self.assertRaisesRegex(lp.PlaybookError, "список play"):
            lp.validate_structure("name: x\nhosts: all\n")
        with self.assertRaisesRegex(lp.PlaybookError, "hosts"):
            lp.validate_structure("- name: x\n  tasks: []\n")
        with self.assertRaisesRegex(lp.PlaybookError, "пустой"):
            lp.validate_structure("  \n")
        self.assertEqual(len(lp.validate_structure(GOOD)), 1)
        lp.validate_structure("- ansible.builtin.import_playbook: other.yml\n")

    def test_template_is_a_valid_playbook(self):
        self.assertIsNone(lp.check(lp.TEMPLATE))

    def test_syntax_check_catches_unknown_module(self):
        if not shutil.which("ansible-playbook"):
            self.skipTest("ansible-playbook нет вне контейнера")
        self.assertIsNone(lp.check(GOOD))
        error = lp.check(GOOD.replace("ansible.windows.win_ping", "ansible.windows.win_pingg"))
        self.assertIsNotNone(error)
        self.assertIn("win_pingg", error)
        self.assertNotIn(self.dir, error)
        self.assertEqual([p.name for p in Path(self.dir).iterdir()], [])  # временный каталог проверки убран

    def test_write_is_atomic_and_ends_with_newline(self):
        target = lp.resolve(self.repo, "install/x.yml")
        lp.write(target, "- hosts: all")
        self.assertEqual(target.read_text(encoding="utf-8"), "- hosts: all\n")
        self.assertEqual(sorted(p.name for p in target.parent.iterdir()), ["x.yml"])
        target.unlink()
        lp.prune_empty_dirs(self.repo, target)
        self.assertFalse(target.parent.exists())
        self.assertTrue(Path(self.dir).exists())


if __name__ == "__main__":
    unittest.main()
