import unittest

from services.ansible_runner import playbook_matched_hosts


class _Result:
    def __init__(self, rc, stats):
        self.rc = rc
        self.stats = stats


class AnsibleRunnerTests(unittest.TestCase):
    def test_clean_run_without_matching_hosts_is_not_successful(self):
        self.assertFalse(playbook_matched_hosts(_Result(0, {}), {"host-1"}))

    def test_clean_run_with_selected_host_is_successful(self):
        self.assertTrue(playbook_matched_hosts(_Result(0, {}), {"host-1"}, {"host-1"}))

    def test_nonzero_return_code_is_failure(self):
        self.assertFalse(playbook_matched_hosts(_Result(2, {"host-1": {}}), {"host-1"}))


if __name__ == "__main__":
    unittest.main()
