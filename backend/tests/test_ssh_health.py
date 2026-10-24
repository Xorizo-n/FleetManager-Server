import hashlib
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from pydantic import ValidationError

from schemas.agent import AgentHeartbeatRequest, AgentSshReport
from services import agent_update, agent_version, ansible_runner
from services.agent_version import agent_update_offer, installer_sha256
from services.ssh_health import host_keys, ssh_blocked_reason, ssh_problems, store_ssh_report

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGxS0mEu5mVvM2oQ"
HEALTHY = {
    "installed": True, "start_type": "auto", "listening": True, "responding": True, "repaired": [],
    "firewall_rule": "ok", "firewall_ignored_on": [], "firewall_gpo_allows": False, "firewall_blocking": [],
    "network_profiles": ["DomainAuthenticated"], "config_valid": True, "config_port": None, "path_ok": True,
    "login_is_admin": True, "domain_trust": "ok", "host_keys": [KEY],
}


def state(**changes):
    return {**HEALTHY, "reported_at": NOW.isoformat(), **changes}


class SshProblemsTests(unittest.TestCase):
    def test_healthy_report_has_no_problems(self):
        self.assertEqual(ssh_problems(state()), [])
        self.assertIsNone(ssh_blocked_reason(state(), NOW))

    def test_no_report_means_unknown_not_blocked(self):
        self.assertEqual(ssh_problems(None), [])
        self.assertIsNone(ssh_blocked_reason(None, NOW))

    def test_old_agent_report_without_new_fields_is_not_misread(self):
        # 2026.10.24 присылает только состояние службы
        old = {"installed": True, "start_type": "auto", "listening": True, "repaired": [], "reported_at": NOW.isoformat()}
        self.assertEqual(ssh_problems(old), [])

    def test_sshd_states(self):
        self.assertIn("не установлен", ssh_problems(state(installed=False))[0])
        self.assertIn("отключена", ssh_problems(state(start_type="disabled", listening=False))[0])
        self.assertIn("не слушает", ssh_problems(state(listening=False))[0])
        self.assertIn("не отвечает", ssh_problems(state(responding=False))[0])

    def test_gpo_that_ignores_local_rules_blocks_only_on_the_active_profile(self):
        domain = state(firewall_ignored_on=["Domain"], network_profiles=["DomainAuthenticated"])
        self.assertIn("групповая политика", ssh_blocked_reason(domain, NOW))
        self.assertIsNone(ssh_blocked_reason(state(firewall_ignored_on=["Public"], network_profiles=["DomainAuthenticated"]), NOW))
        self.assertIsNone(ssh_blocked_reason(state(firewall_ignored_on=["Domain"], firewall_gpo_allows=True), NOW))

    def test_firewall_logon_and_trust_problems_block(self):
        for changes in ({"firewall_rule": "missing"}, {"firewall_blocking": ["Block SSH"]},
                        {"login_is_admin": False}, {"domain_trust": "broken"}):
            with self.subTest(changes=changes):
                self.assertIsNotNone(ssh_blocked_reason(state(**changes), NOW))

    def test_unreachable_domain_controller_is_not_a_problem(self):
        self.assertEqual(ssh_problems(state(domain_trust="unreachable")), [])

    def test_path_and_config_are_shown_but_do_not_hold_tasks(self):
        report = state(path_ok=False, config_valid=False, config_port=2222)
        self.assertEqual(len(ssh_problems(report)), 3)
        self.assertIsNone(ssh_blocked_reason(report, NOW))

    def test_stale_report_is_not_used_for_decisions(self):
        stale = state(listening=False, reported_at=(NOW - timedelta(hours=1)).isoformat())
        self.assertIsNone(ssh_blocked_reason(stale, NOW))
        self.assertTrue(ssh_problems(stale))


class SshReportSchemaTests(unittest.TestCase):
    def test_store_keeps_report_and_time(self):
        host = SimpleNamespace(ssh_state=None)
        store_ssh_report(host, AgentSshReport(**HEALTHY), NOW)
        self.assertEqual(host.ssh_state["reported_at"], NOW.isoformat())
        self.assertEqual(host_keys(host.ssh_state), [KEY])

    def test_host_keys_are_sanitized_for_known_hosts(self):
        report = AgentSshReport(host_keys=[KEY + " system@PC", "ssh-rsa AAAA\nevil-host ssh-rsa AAAA", "garbage", "ssh-ed25519 short"])
        self.assertEqual(report.host_keys, [KEY])

    def test_nulls_from_powershell_become_empty_lists(self):
        self.assertEqual(AgentSshReport(firewall_ignored_on=None, host_keys=None).firewall_ignored_on, [])

    def test_heartbeat_accepts_old_and_new_ssh_objects(self):
        base = {"machine_id": str(uuid.uuid4()), "os": "windows_11"}
        self.assertIsNone(AgentHeartbeatRequest(**base).ssh)
        self.assertTrue(AgentHeartbeatRequest(**base, ssh={"installed": True, "start_type": "auto", "listening": True, "repaired": []}).ssh.listening)
        self.assertEqual(AgentHeartbeatRequest(**base, ssh=HEALTHY).ssh.host_keys, [KEY])
        with self.assertRaises(ValidationError):
            AgentHeartbeatRequest(**base, ssh={"config_port": 70000})


class AgentUpdateOfferTests(unittest.TestCase):
    def setUp(self):
        self.soft = tempfile.TemporaryDirectory()
        self.addCleanup(self.soft.cleanup)
        patcher = mock.patch.object(agent_version.settings, "soft_share_dir", self.soft.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        with open(os.path.join(self.soft.name, agent_version.INSTALLER_FILENAME), "wb") as f:
            f.write(b"installer")
        with open(os.path.join(self.soft.name, agent_version.VERSION_SIDECAR), "w", encoding="utf-8") as f:
            f.write("2026.10.25.24")

    def test_sha256_of_the_served_installer(self):
        self.assertEqual(installer_sha256(), hashlib.sha256(b"installer").hexdigest())

    def test_no_target_no_offer(self):
        host = SimpleNamespace(agent_update_target=None)
        self.assertIsNone(agent_update_offer(host, "2026.10.24.23"))

    def test_outdated_agent_gets_the_available_installer(self):
        host = SimpleNamespace(agent_update_target="2026.10.25.24")
        offer = agent_update_offer(host, "2026.10.25.1")
        self.assertEqual(offer, {"version": "2026.10.25.24", "sha256": installer_sha256()})

    def test_reaching_the_target_clears_it(self):
        host = SimpleNamespace(agent_update_target="2026.10.25.24")
        self.assertIsNone(agent_update_offer(host, "2026.10.25.24"))
        self.assertIsNone(host.agent_update_target)

    def test_unknown_agent_version_gets_nothing(self):
        host = SimpleNamespace(agent_update_target="2026.10.25.24")
        self.assertIsNone(agent_update_offer(host, None))
        self.assertEqual(host.agent_update_target, "2026.10.25.24")

    def test_unreachable_host_is_delegated_to_its_agent(self):
        db = mock.Mock()
        host = SimpleNamespace(agent_version="2026.10.25.1", agent_update_target=None)
        self.assertIn("агент сам поставит", agent_update._delegate_to_agent(db, host, "2026.10.25.24"))
        self.assertEqual(host.agent_update_target, "2026.10.25.24")
        db.commit.assert_called_once()

    def test_agent_too_old_to_update_itself_is_named(self):
        host = SimpleNamespace(agent_version="2026.10.24.23", agent_update_target=None)
        self.assertIn("установка на месте", agent_update._delegate_to_agent(mock.Mock(), host, "2026.10.25.24"))

    def test_up_to_date_host_is_not_delegated(self):
        host = SimpleNamespace(agent_version="2026.10.25.24", agent_update_target=None)
        self.assertEqual(agent_update._delegate_to_agent(mock.Mock(), host, "2026.10.25.24"), "")
        self.assertIsNone(host.agent_update_target)


class KnownHostArgsTests(unittest.TestCase):
    def test_host_without_reported_keys_keeps_default_checking(self):
        self.assertEqual(ansible_runner.known_host_args(SimpleNamespace(id=uuid.uuid4(), ssh_state=None)), "")

    def test_reported_keys_are_pinned_to_the_host_id(self):
        host = SimpleNamespace(id=uuid.uuid4(), ssh_state=state())
        with tempfile.TemporaryDirectory() as keys_dir, mock.patch.object(ansible_runner.settings, "ansible_private_key_dir", keys_dir):
            args = ansible_runner.known_host_args(host)
            path = os.path.join(keys_dir, "known_hosts", str(host.id))
            self.assertIn(f"-o HostKeyAlias={host.id}", args)
            self.assertIn(f"-o UserKnownHostsFile={path}", args)
            self.assertIn("StrictHostKeyChecking=yes", args)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), f"{host.id} {KEY}\n")


if __name__ == "__main__":
    unittest.main()
