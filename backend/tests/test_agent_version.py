import os
import tempfile
import unittest
import uuid
from unittest import mock

from services import agent_version
from services.agent_version import (
    STATUS_NO_AGENT,
    STATUS_NEWER,
    STATUS_OUTDATED,
    STATUS_UNKNOWN,
    STATUS_UP_TO_DATE,
    agent_version_from_software,
    available_agent_version,
    compare_versions,
    normalize_version,
    parse_version,
    version_status,
)
from services import agent_update
from services.agent_update import (
    PROBE_CMD,
    PROBE_TIMEOUT,
    TCP_CHECK_TIMEOUT,
    UPDATE_CMD,
    UPDATE_TIMEOUT,
    _is_reachable,
    _ssh_port,
    encode_powershell,
    parse_probe_output,
)


class AgentVersionParsingTests(unittest.TestCase):
    def test_release_tag_is_normalized_to_bare_version(self):
        self.assertEqual(normalize_version(" v2025.08.14.12 "), "2025.08.14.12")
        self.assertEqual(normalize_version("2025.08.14.12"), "2025.08.14.12")
        self.assertIsNone(normalize_version("   "))
        self.assertIsNone(normalize_version(None))

    def test_versions_compare_numerically_not_lexicographically(self):
        # "2025.08.09.9" > "2025.08.09.10" при строковом сравнении — здесь нет.
        self.assertEqual(compare_versions("2025.08.09.9", "2025.08.09.10"), -1)
        self.assertEqual(compare_versions("v2025.08.14.12", "2025.08.14.12"), 0)
        self.assertEqual(compare_versions("2026.01.01.1", "2025.12.31.99"), 1)

    def test_shorter_version_is_padded_with_zeros(self):
        self.assertEqual(compare_versions("1.0", "1.0.0.0"), 0)
        self.assertEqual(parse_version("1.0"), (1, 0))

    def test_unparsable_versions_do_not_compare(self):
        self.assertIsNone(compare_versions("dev", "2025.08.14.12"))
        self.assertIsNone(parse_version("dev"))


class AgentVersionStatusTests(unittest.TestCase):
    def test_host_without_agent_is_reported_separately(self):
        self.assertEqual(version_status(None, "2025.08.14.12", has_agent=False), STATUS_NO_AGENT)

    def test_missing_version_on_either_side_is_unknown(self):
        self.assertEqual(version_status(None, "2025.08.14.12"), STATUS_UNKNOWN)
        self.assertEqual(version_status("2025.08.14.12", None), STATUS_UNKNOWN)

    def test_outdated_up_to_date_and_newer(self):
        self.assertEqual(version_status("2025.08.01.3", "2025.08.14.12"), STATUS_OUTDATED)
        self.assertEqual(version_status("2025.08.14.12", "v2025.08.14.12"), STATUS_UP_TO_DATE)
        self.assertEqual(version_status("2025.09.01.1", "2025.08.14.12"), STATUS_NEWER)

    def test_non_numeric_versions_match_only_exactly(self):
        self.assertEqual(version_status("dev", "dev"), STATUS_UP_TO_DATE)
        self.assertEqual(version_status("dev", "2025.08.14.12"), STATUS_UNKNOWN)


class AvailableVersionTests(unittest.TestCase):
    def test_available_version_is_read_from_installer_sidecar(self):
        with tempfile.TemporaryDirectory() as soft_dir:
            sidecar = os.path.join(soft_dir, agent_version.VERSION_SIDECAR)
            with open(sidecar, "w", encoding="utf-8") as f:
                f.write("v2025.08.14.12\n")
            with mock.patch.object(agent_version.settings, "soft_share_dir", soft_dir):
                self.assertEqual(available_agent_version(), "2025.08.14.12")

    def test_missing_sidecar_yields_no_available_version(self):
        with tempfile.TemporaryDirectory() as soft_dir:
            with mock.patch.object(agent_version.settings, "soft_share_dir", soft_dir):
                self.assertIsNone(available_agent_version())


class AgentVersionFromSoftwareTests(unittest.TestCase):
    def test_agent_version_is_recovered_from_software_inventory(self):
        items = [("7-Zip", "24.0"), ("FleetManager Agent", "2025.08.14.12")]
        self.assertEqual(agent_version_from_software(items), "2025.08.14.12")

    def test_lookup_is_case_insensitive_and_tolerates_absence(self):
        self.assertEqual(agent_version_from_software([("fleetmanager agent", "v1.0")]), "1.0")
        self.assertIsNone(agent_version_from_software([("7-Zip", "24.0")]))


class AgentUpdateScriptTests(unittest.TestCase):
    def test_scripts_are_passed_as_encoded_powershell(self):
        for command in (PROBE_CMD, UPDATE_CMD):
            self.assertTrue(command.startswith("powershell -NoProfile -NonInteractive -EncodedCommand "))

    def test_encoded_command_round_trips_as_utf16(self):
        import base64

        encoded = encode_powershell("Write-Output 'ok'").rsplit(" ", 1)[1]
        self.assertEqual(base64.b64decode(encoded).decode("utf-16le"), "Write-Output 'ok'")

    def test_update_script_uses_host_own_credentials_and_never_server_secrets(self):
        import base64

        script = base64.b64decode(UPDATE_CMD.rsplit(" ", 1)[1]).decode("utf-16le")
        self.assertIn("agent.json", script)
        self.assertIn("$config.AgentToken", script)
        self.assertIn("/api/agent/installer", script)
        self.assertIn("/VERYSILENT", script)
        self.assertNotIn("EnrollmentToken", script)

    def test_installer_runs_outside_the_ssh_session(self):
        # Win32-OpenSSH kills every process of a session when it ends. An installer
        # started with Start-Process died as soon as the script returned and left
        # SU5-D206-TEMP with the service stopped; it has to be started through WMI.
        import base64

        script = base64.b64decode(UPDATE_CMD.rsplit(" ", 1)[1]).decode("utf-16le")
        self.assertNotIn("Start-Process", script)
        self.assertIn("Invoke-CimMethod -ClassName Win32_Process -MethodName Create", script)

    def test_update_waits_for_the_installer_not_for_the_registry(self):
        # An Inno install already has the old version in the registry, so waiting
        # for "a version to appear" returned at once, before the installer ran.
        import base64

        script = base64.b64decode(UPDATE_CMD.rsplit(" ", 1)[1]).decode("utf-16le")
        self.assertIn("$process.HasExited", script)
        self.assertIn("$null = $process.Handle", script)
        self.assertRegex(script, r"deadline\s*=\s*\(Get-Date\)\.AddSeconds\(900\)")
        self.assertNotIn("while (-not $version", script)
        for field in ("previous_version", "finished", "exit_code"):
            self.assertIn(field, script)

    def test_commands_fit_the_ssh_command_line(self):
        # Over SSH a command of ~14k characters is dropped as "unreachable", 9k still passes.
        for command in (PROBE_CMD, UPDATE_CMD):
            self.assertLess(len(command), 8000)

    def test_host_takes_the_installer_ssh_port_after_update(self):
        # Old agents reported random SSH ports (MR32-440-09: 44596); the installer
        # moves sshd to 22 and the new agent no longer reports a port.
        from types import SimpleNamespace

        from services.agent_update import INSTALLER_SSH_PORT, _adopt_installer_ssh_port

        db = SimpleNamespace(commit=lambda: None)
        task = SimpleNamespace(log_output="")
        host = SimpleNamespace(hostname="MR32-440-09", ip_address=None, id="h", ssh_port=44596)
        self.assertTrue(_adopt_installer_ssh_port(db, task, host))
        self.assertEqual(host.ssh_port, INSTALLER_SSH_PORT)
        self.assertIn("44596 → 22", task.log_output)
        self.assertFalse(_adopt_installer_ssh_port(db, task, host))

    def _recheck(self, open_ports):
        from types import SimpleNamespace
        from unittest import mock

        from services import agent_update

        db = SimpleNamespace(commit=lambda: None)
        task = SimpleNamespace(log_output="")
        host = SimpleNamespace(hostname="MR32-044-SERGEY", ip_address="10.40.161.34", id="h", ssh_port=5022)
        probe = '{"version":"2026.10.10.9","service_status":"Running"}'
        with mock.patch.object(agent_update.time, "sleep"),                 mock.patch.object(agent_update, "_is_reachable", side_effect=lambda h, port=None: (port or h.ssh_port) in open_ports),                 mock.patch.object(agent_update, "build_full_inventory", return_value={}),                 mock.patch.object(agent_update, "run_raw_command", return_value=probe):
            confirmed = agent_update._recheck_version(db, task, {}, host, "2026.10.10.9")
        return host, confirmed

    def test_connection_lost_before_the_install_keeps_the_port(self):
        # MR32-044-SERGEY: the session was reset on 5022 before anything ran.
        host, confirmed = self._recheck(open_ports={5022})
        self.assertEqual(host.ssh_port, 5022)
        self.assertEqual(confirmed, "2026.10.10.9")

    def test_sshd_moved_by_the_installer_switches_the_port(self):
        host, confirmed = self._recheck(open_ports={22})
        self.assertEqual(host.ssh_port, 22)
        self.assertEqual(confirmed, "2026.10.10.9")

    def test_nothing_open_keeps_the_port_and_fails(self):
        host, confirmed = self._recheck(open_ports=set())
        self.assertEqual(host.ssh_port, 5022)
        self.assertIsNone(confirmed)

    def test_probe_script_reads_the_inno_setup_uninstall_entry(self):
        import base64

        script = base64.b64decode(PROBE_CMD.rsplit(" ", 1)[1]).decode("utf-16le")
        self.assertIn("DisplayVersion", script)
        self.assertIn("FleetManager Agent", script)
        self.assertIn("WOW6432Node", script)

    def test_probe_output_is_extracted_from_noisy_ssh_output(self):
        raw = 'motd banner\r\n{"version":"2025.08.14.12","service_status":"Running"}\r\n'
        self.assertEqual(parse_probe_output(raw)["version"], "2025.08.14.12")

    def test_probe_output_without_json_is_empty(self):
        self.assertEqual(parse_probe_output("agent not installed"), {})
        self.assertEqual(parse_probe_output(""), {})


class _FakeHost:
    def __init__(self, hostname=None, ip_address=None, ssh_port=None):
        self.hostname = hostname
        self.ip_address = ip_address
        self.ssh_port = ssh_port


class AgentUnreachableHostTests(unittest.TestCase):
    """An unreachable host used to stall run_agent_update for up to UPDATE_TIMEOUT
    (30 min) plus the disconnect-recovery retries, because nothing failed fast
    before handing the host to ansible-runner. _is_reachable is the fast-fail
    gate both run_agent_version_scan and run_agent_update check first."""

    def test_tcp_check_is_far_shorter_than_the_ssh_job_timeouts(self):
        self.assertLess(TCP_CHECK_TIMEOUT, PROBE_TIMEOUT)
        self.assertLess(TCP_CHECK_TIMEOUT, UPDATE_TIMEOUT)

    def test_ssh_port_falls_back_to_the_ansible_default(self):
        self.assertEqual(_ssh_port(_FakeHost(ssh_port=None)), agent_update.settings.ansible_ssh_port)
        self.assertEqual(_ssh_port(_FakeHost(ssh_port=2222)), 2222)

    def test_default_agent_ssh_port_is_22(self):
        # FleetManager-Agent keeps sshd on 22 (firewalled to this server) and does
        # not report its port at registration, so the default must match it.
        self.assertEqual(type(agent_update.settings).model_fields["ansible_ssh_port"].default, 22)

    def test_reachable_host_opens_a_socket_on_its_ssh_port(self):
        host = _FakeHost(hostname="pc-01.example.local", ssh_port=5022)
        with mock.patch.object(agent_update.socket, "create_connection") as create_connection:
            create_connection.return_value.__enter__ = mock.Mock(return_value=mock.Mock())
            create_connection.return_value.__exit__ = mock.Mock(return_value=False)
            self.assertTrue(_is_reachable(host))
            create_connection.assert_called_once_with(("pc-01.example.local", 5022), timeout=TCP_CHECK_TIMEOUT)

    def test_unreachable_host_fails_fast_without_raising(self):
        host = _FakeHost(ip_address="10.40.1.20")
        with mock.patch.object(agent_update.socket, "create_connection", side_effect=OSError("timed out")):
            self.assertFalse(_is_reachable(host))

    def test_host_without_hostname_or_ip_is_reported_unreachable(self):
        self.assertFalse(_is_reachable(_FakeHost()))


class AgentVersionSchemaTests(unittest.TestCase):
    def test_heartbeat_accepts_optional_agent_version(self):
        from schemas.agent import AgentHeartbeatRequest

        payload = AgentHeartbeatRequest(machine_id=str(uuid.uuid4()), os="windows_11", agent_version=" 2025.08.14.12 ")
        self.assertEqual(payload.agent_version, "2025.08.14.12")

        legacy = AgentHeartbeatRequest(machine_id=str(uuid.uuid4()), os="windows_11")
        self.assertIsNone(legacy.agent_version)

    def test_host_selection_defaults_to_all_agent_hosts(self):
        from schemas.agent import AgentHostSelection

        self.assertEqual(AgentHostSelection().host_ids, [])


if __name__ == "__main__":
    unittest.main()
