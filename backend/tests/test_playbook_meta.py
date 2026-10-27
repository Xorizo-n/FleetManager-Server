import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from config import settings
from services import playbook_meta
from services.playbook_meta import playbook_meta as meta_of, read_meta, share_files

PLAYBOOK = """---
- name: "Notepad++"
  hosts: Win_Hosts
  vars:
    fm_description: >-
      Текстовый редактор
      для кода.
    fm_files:
      - 'npp.*.Installer.x64.msi'
      - 'netfx3/*.cab'
      - 'dbeaver-drivers/'
  tasks: []
"""


class PlaybookMetaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "repo" / "playbooks").mkdir(parents=True)
        self.share = self.root / "share"
        (self.share / "netfx3").mkdir(parents=True)
        (self.share / "npp.8.9.8.Installer.x64.msi").write_text("x")
        (self.share / "npp.8.9.9.Installer.x64.msi").write_text("x")
        patcher = mock.patch.object(settings, "soft_share_dir", str(self.share))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def write(self, text, name="playbooks/install_npp.yml"):
        path = self.root / "repo" / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_title_description_and_files(self):
        meta = read_meta(self.write(PLAYBOOK))
        self.assertEqual(meta.title, "Notepad++")
        self.assertEqual(meta.description, "Текстовый редактор для кода.")
        self.assertEqual(meta.files, ("npp.*.Installer.x64.msi", "netfx3/*.cab", "dbeaver-drivers/"))

    def test_share_presence(self):
        self.assertEqual(share_files(("npp.*.Installer.x64.msi", "netfx3/*.cab", "dbeaver-drivers/")), [
            # плейбук берёт самый новый по имени — его и показываем
            {"pattern": "npp.*.Installer.x64.msi", "present": True, "found": "npp.8.9.9.Installer.x64.msi"},
            {"pattern": "netfx3/*.cab", "present": False, "found": None},
            {"pattern": "dbeaver-drivers/", "present": False, "found": None},
        ])

    def test_patterns_outside_the_share_are_never_present(self):
        self.assertFalse(share_files(("../repo/playbooks/*.yml",))[0]["present"])
        self.assertFalse(share_files(("/etc/passwd",))[0]["present"])

    def test_playbook_without_metadata(self):
        meta = read_meta(self.write("---\n- name: Install X\n  hosts: all\n  tasks: []\n"))
        self.assertEqual((meta.title, meta.description, meta.files), ("Install X", None, ()))

    def test_broken_yaml_gives_empty_meta(self):
        self.assertEqual(read_meta(self.write("- name: [unclosed\n")), playbook_meta.PlaybookMeta())

    def test_reparsed_after_change(self):
        path = self.write(PLAYBOOK)
        self.assertEqual(read_meta(path).title, "Notepad++")
        path.write_text(PLAYBOOK.replace('"Notepad++"', '"Notepad++ 9"'), encoding="utf-8")
        os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000))
        self.assertEqual(read_meta(path).title, "Notepad++ 9")

    def test_task_path_stays_inside_the_repo(self):
        self.write(PLAYBOOK)
        repo = str(self.root / "repo")
        self.assertEqual(meta_of(repo, "playbooks/install_npp.yml").title, "Notepad++")
        self.assertIsNone(meta_of(repo, "../share/x.yml").title)
        self.assertIsNone(meta_of(None, "playbooks/install_npp.yml").title)


if __name__ == "__main__":
    unittest.main()
