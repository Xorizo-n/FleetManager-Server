import subprocess
import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

from config import settings
from services import run_as


def user(**kw):
    base = dict(username="Sergey.Mirzagitov", auth_source="ldap", is_active=True)
    return SimpleNamespace(**{**base, **kw})


class FakeDb:
    def __init__(self, users):
        self.users = users

    def get(self, _model, key):
        return self.users.get(key)


class InitiatorTests(unittest.TestCase):
    def setUp(self):
        self.uid = uuid.uuid4()
        p = mock.patch("services.ldap_config.current", return_value=SimpleNamespace(enabled=True))
        p.start()
        self.addCleanup(p.stop)

    def login(self, u, **settings_kw):
        with mock.patch.multiple(settings, **{"playbook_run_as_initiator": True, "ldap_netbios_domain": "AT", **settings_kw}):
            return run_as.initiator_login(FakeDb({self.uid: u}), self.uid)

    def test_domain_user_gets_netbios_login(self):
        self.assertEqual(self.login(user()), ("AT\\Sergey.Mirzagitov", None))

    def test_local_blocked_missing_and_disabled_feature_fall_back(self):
        self.assertIn("локальная", self.login(user(auth_source="local"))[1])
        self.assertIn("заблокирован", self.login(user(is_active=False))[1])
        self.assertIn("удалён", self.login(None)[1])
        self.assertIn("выключен", self.login(user(), playbook_run_as_initiator=False)[1])
        with mock.patch.multiple(settings, playbook_run_as_initiator=True):
            self.assertIn("нет инициатора", run_as.initiator_login(FakeDb({}), None)[1])

    def test_domain_login_closed_falls_back(self):
        with mock.patch("services.ldap_config.current", return_value=SimpleNamespace(enabled=False)):
            self.assertIn("вход через домен", self.login(user())[1])


class ProbeTests(unittest.TestCase):
    host = SimpleNamespace(id=uuid.uuid4(), hostname="SU5-K104-W09", ip_address="10.152.3.64", ssh_port=22)

    def probe(self, returncode=0, stdout="at\\sergey.mirzagitov\r\n", stderr="", exc=None):
        run = mock.Mock(side_effect=exc) if exc else mock.Mock(return_value=SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr))
        with mock.patch.object(run_as, "_ssh_key", return_value="/keys/k.pem"), mock.patch("subprocess.run", run):
            return run_as.probe_host(self.host, "AT\\Sergey.Mirzagitov"), run

    def test_success_when_whoami_matches_case_insensitive(self):
        error, run = self.probe()
        self.assertIsNone(error)
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("-l") + 1], "AT\\Sergey.Mirzagitov")
        self.assertIn("BatchMode=yes", args)
        self.assertIn("PasswordAuthentication=no", args)

    def test_failures_are_explained(self):
        self.assertIn("администраторах", self.probe(255, "", "AT\\x@host: Permission denied (publickey).")[0])
        self.assertIn("недоступен", self.probe(255, "", "ssh: connect to host x port 22: Connection timed out")[0])
        self.assertIn("ключ", self.probe(255, "", "@@@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @@@")[0])
        self.assertIn("другой учёткой", self.probe(0, "su5-k104-w09\\admin")[0])
        self.assertIn("вовремя", self.probe(exc=subprocess.TimeoutExpired("ssh", 75))[0])

    def test_no_key_no_probe(self):
        with mock.patch.object(run_as, "_ssh_key", return_value=None), mock.patch("subprocess.run") as run:
            self.assertIn("SSH-ключа", run_as.probe_host(self.host, "AT\\x"))
        run.assert_not_called()


class PlanTests(unittest.TestCase):
    def test_split_between_initiator_and_fallback(self):
        hosts = [SimpleNamespace(id=uuid.uuid4(), hostname=f"PC{i}") for i in range(3)]
        query = mock.Mock()
        query.filter.return_value.all.return_value = hosts
        db = mock.Mock()
        db.query.return_value = query
        verdicts = {hosts[0].id: None, hosts[1].id: "ПК недоступен по SSH", hosts[2].id: None}
        with mock.patch.object(run_as, "initiator_login", return_value=("AT\\U", None)), \
                mock.patch.object(run_as, "_probe", side_effect=lambda h, login: (verdicts[h.id], False)):
            plan = run_as.plan(db, [str(h.id) for h in hosts], uuid.uuid4())
        self.assertEqual(plan.as_user, {str(hosts[0].id), str(hosts[2].id)})
        self.assertEqual(plan.fallback, {str(hosts[1].id): "ПК недоступен по SSH"})
        self.assertEqual(plan.overrides(), {str(hosts[0].id): "AT\\U", str(hosts[2].id): "AT\\U"})
        lines = run_as.log_lines(plan, {str(h.id): h.hostname for h in hosts})
        self.assertIn("от имени AT\\U на 2 ПК", lines[0])
        self.assertIn("PC1: ПК недоступен по SSH", lines[2])

    def test_no_initiator_means_no_probe(self):
        with mock.patch.object(run_as, "initiator_login", return_value=(None, "у задачи нет инициатора")), \
                mock.patch.object(run_as, "probe_host") as probe:
            plan = run_as.plan(mock.Mock(), ["x"], None)
        probe.assert_not_called()
        self.assertEqual(plan.overrides(), {})
        self.assertEqual(run_as.log_lines(plan, {}), ["[Fleet Manager] Выполняется от учётки установки агента: у задачи нет инициатора."])



class LocalAdminFallbackTests(unittest.TestCase):
    """Вход отклонён под доменными учётками — плейбук идёт под локальным администратором (services/local_admin.py)."""

    host = SimpleNamespace(id=uuid.uuid4(), hostname="SU5-I203-W03", ip_address="10.152.132.9", ssh_port=22, ssh_state={"local_admin": "ok"},
                           credential=SimpleNamespace(login="at\\Sergey.Mirzagitov"))
    RESET = ("вход не удался: Connection reset by 10.152.132.9 port 22", True)
    TIMEOUT = ("ПК недоступен по SSH", False)

    def decide(self, answers, login="AT\\Ivan.Petrov", **host_kw):
        host = SimpleNamespace(**{**vars(self.host), **host_kw})
        probe = mock.Mock(side_effect=lambda h, who: answers[who.lower()])
        with mock.patch.object(run_as, "_probe", probe), mock.patch.multiple(settings, local_admin_fallback=True, local_admin_login="admin"):
            return run_as._decide(host, login), [c.args[1] for c in probe.call_args_list]

    def test_domain_down_goes_local(self):
        verdict, tried = self.decide({"at\\ivan.petrov": self.RESET, "at\\sergey.mirzagitov": self.RESET, "admin": (None, False)})
        self.assertEqual(verdict[0], "local")
        self.assertEqual(tried, ["AT\\Ivan.Petrov", "at\\Sergey.Mirzagitov", "admin"])

    def test_initiator_not_admin_keeps_the_install_account(self):
        verdict, tried = self.decide({"at\\ivan.petrov": ("вход не принят", True), "at\\sergey.mirzagitov": (None, False)})
        self.assertEqual(verdict[0], "fallback")
        self.assertNotIn("admin", tried)

    def test_network_failure_tries_nothing_else(self):
        verdict, tried = self.decide({"at\\ivan.petrov": self.TIMEOUT})
        self.assertEqual((verdict[0], tried), ("fallback", ["AT\\Ivan.Petrov"]))

    def test_initiator_is_the_install_account(self):
        verdict, tried = self.decide({"at\\sergey.mirzagitov": self.RESET, "admin": (None, False)}, login="at\\Sergey.Mirzagitov")
        self.assertEqual((verdict[0], tried), ("local", ["at\\Sergey.Mirzagitov", "admin"]))

    def test_agent_says_no_local_account(self):
        verdict, tried = self.decide({"at\\ivan.petrov": self.RESET}, ssh_state={"local_admin": "disabled"})
        self.assertEqual((verdict[0], tried), ("fallback", ["AT\\Ivan.Petrov"]))

    def test_local_login_whoami_has_the_computer_name(self):
        run = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout="su5-i203-w03\\admin\r\n", stderr=""))
        with mock.patch.object(run_as, "_ssh_key", return_value="/keys/k.pem"), mock.patch("subprocess.run", run):
            self.assertIsNone(run_as.probe_host(self.host, "admin"))

    def test_plan_overrides_and_log(self):
        plan = run_as.RunAsPlan(login="AT\\U", as_user={"a"}, local={"b": "вход не удался: Connection reset"})
        with mock.patch.multiple(settings, local_admin_fallback=True, local_admin_login="admin"):
            self.assertEqual(plan.overrides(), {"a": "AT\\U", "b": "admin"})
            lines = run_as.log_lines(plan, {"a": "PC-A", "b": "PC-B"})
        self.assertIn("Под локальным администратором admin на 1 ПК", lines[1])
        self.assertIn("PC-B: вход не удался", lines[2])


if __name__ == "__main__":
    unittest.main()
