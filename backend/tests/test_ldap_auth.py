import unittest
import uuid
from unittest import mock

from config import settings
from models.user import UserRole
from services import ldap_auth, ldap_config

ADMINS = "CN=FM-Admins,OU=Groups,DC=at,DC=urfu,DC=ru"
VIEWERS = "CN=FM-Viewers,OU=Groups,DC=at,DC=urfu,DC=ru"
USER_DN = "CN=Иванов Иван,OU=Staff,DC=at,DC=urfu,DC=ru"
GUID = str(uuid.uuid4())


class FakeEntry:
    def __init__(self, dn, attrs):
        self.entry_dn = dn
        self.entry_attributes_as_dict = attrs


class FakeConn:
    """Каталог из одной записи (copies — сколько одинаковых): поиск по логину/objectGUID и членство в группах."""

    def __init__(self, groups=(), disabled=False, copies=1):
        self.groups = set(groups)
        self.copies = copies
        self.attrs = {
            "sAMAccountName": ["ivanov"],
            "cn": ["Иванов Иван"],
            "mail": ["I.I.Ivanov@urfu.ru"],
            "userPrincipalName": ["i.i.ivanov@urfu.ru"],
            "displayName": ["Иванов Иван"],
            "userAccountControl": [514 if disabled else 512],
            "objectGUID": ["{" + GUID + "}"],
        }
        self.entries = []
        self.filters = []
        self.unbound = False

    def search(self, base, search_filter, scope, attributes=None, size_limit=0):
        self.filters.append(search_filter)
        self.entries = []
        if search_filter.startswith(f"(memberOf:{ldap_auth.IN_CHAIN}:="):
            group = search_filter[len(f"(memberOf:{ldap_auth.IN_CHAIN}:="):-1]
            if base == USER_DN and group in self.groups:
                self.entries = [FakeEntry(USER_DN, {})]
        elif self.matches(search_filter) or search_filter.startswith("(objectGUID="):
            self.entries = [FakeEntry(USER_DN, self.attrs)] * self.copies
        return bool(self.entries)

    def matches(self, search_filter):
        a = {k: v[0] for k, v in self.attrs.items()}
        atoms = [f"(sAMAccountName={a['sAMAccountName']})", f"(cn={a['cn']})", f"(userPrincipalName={a['userPrincipalName']})",
                 f"(mail={a['mail']})", f"(userPrincipalName={a['userPrincipalName'].split('@')[0]}@*)", f"(mail={a['mail'].split('@')[0]}@*)"]
        return any(atom.lower() in search_filter.lower() for atom in atoms)

    def unbind(self):
        self.unbound = True


class LdapAuthTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.multiple(settings, ldap_enabled=True, ldap_domain="at.urfu.ru", ldap_bind_dn="",
                                      ldap_bind_password="", ldap_admin_groups=ADMINS, ldap_operator_groups="",
                                      ldap_viewer_groups=VIEWERS)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Без БД: действуют настройки из .env (их и подменяют тесты)
        current = mock.patch.object(ldap_config, "current", side_effect=lambda: ldap_config._draft.get() or ldap_config.from_settings())
        current.start()
        self.addCleanup(current.stop)

    def bind_as(self, conn, password="secret"):
        """Подменяет bind: верный пароль у ivanov и у служебной записи, остальное — неверный пароль."""
        calls = []

        def fake_bind(user, pwd, timeout=None):
            calls.append(user)
            return conn if pwd == password else None

        return mock.patch.object(ldap_auth, "_bind", side_effect=fake_bind), calls

    def test_normalize_login_strips_domain_prefix(self):
        self.assertEqual(ldap_auth.normalize_login(r"AT\ivanov"), "ivanov")
        self.assertEqual(ldap_auth.normalize_login(" i.i.ivanov@urfu.ru "), "i.i.ivanov@urfu.ru")
        self.assertEqual(ldap_auth.normalize_login("Иванов Иван"), "Иванов Иван")

    def test_normalize_login_rejects_filter_syntax(self):
        self.assertIsNone(ldap_auth.normalize_login("*)(objectClass=*"))
        self.assertIsNone(ldap_auth.normalize_login("a@b@c"))
        self.assertIsNone(ldap_auth.normalize_login(""))

    def test_login_matches_go_from_exact_to_loose(self):
        self.assertEqual([how for how, _ in ldap_auth.login_matches("m.i.rapoport")], ["логин Windows", "имя записи", "UPN или почта без домена"])
        self.assertEqual(ldap_auth.login_matches("m.i.rapoport")[2][1], "(|(userPrincipalName=m.i.rapoport@*)(mail=m.i.rapoport@*))")
        self.assertEqual([how for how, _ in ldap_auth.login_matches("m.i.rapoport@urfu.ru")], ["UPN или почта"])
        # @домен AD — это и неявный UPN: sAMAccountName@at.urfu.ru
        self.assertEqual(ldap_auth.login_matches("Mikhail.Rapoport@at.urfu.ru")[0], ("логин Windows", "(sAMAccountName=Mikhail.Rapoport)"))

    def test_every_login_form_finds_the_same_account(self):
        conn = FakeConn(groups=[ADMINS])
        with mock.patch.multiple(settings, ldap_bind_dn="CN=svc-fleet,DC=at,DC=urfu,DC=ru", ldap_bind_password="secret"):
            for login in ("ivanov", r"AT\ivanov", "ivanov@at.urfu.ru", "Иванов Иван", "i.i.ivanov", "i.i.ivanov@urfu.ru", "I.I.IVANOV@URFU.RU"):
                patch, calls = self.bind_as(conn)
                with patch:
                    identity = ldap_auth.authenticate(login, "secret")
                self.assertEqual((identity.username, calls[-1]), ("ivanov", USER_DN), login)

    def test_timeout_in_the_middle_of_a_search_is_domain_unavailable(self):
        from ldap3.core.exceptions import LDAPSocketReceiveError

        conn = FakeConn(groups=[ADMINS])
        conn.search = mock.Mock(side_effect=LDAPSocketReceiveError("The read operation timed out"))
        patch, _ = self.bind_as(conn)
        with patch, self.assertRaises(ldap_auth.LdapUnavailable):
            ldap_auth.authenticate("ivanov", "secret")

    def test_ambiguous_login_is_denied(self):
        conn = FakeConn(groups=[ADMINS], copies=2)
        with mock.patch.multiple(settings, ldap_bind_dn="CN=svc-fleet,DC=at,DC=urfu,DC=ru", ldap_bind_password="secret"):
            patch, calls = self.bind_as(conn)
            with patch, self.assertRaisesRegex(ldap_auth.LdapDenied, "несколько"):
                ldap_auth.authenticate("Иванов Иван", "secret")
        self.assertNotIn(USER_DN, calls)

    def test_without_service_account_upn_binds_as_is(self):
        patch, calls = self.bind_as(FakeConn(groups=[ADMINS]))
        with patch:
            self.assertEqual(ldap_auth.authenticate("i.i.ivanov@urfu.ru", "secret").username, "ivanov")
        self.assertEqual(calls, ["i.i.ivanov@urfu.ru"])

    def test_role_groups_split_on_semicolon_because_dn_has_commas(self):
        with mock.patch.object(settings, "ldap_admin_groups", f"{ADMINS}; CN=Other,DC=at,DC=urfu,DC=ru"):
            groups = dict(ldap_auth.role_groups())
        self.assertEqual(groups[UserRole.admin], [ADMINS, "CN=Other,DC=at,DC=urfu,DC=ru"])
        self.assertEqual(groups[UserRole.operator], [])

    def test_user_bind_with_implicit_upn_and_highest_role(self):
        conn = FakeConn(groups=[ADMINS, VIEWERS])
        patch, calls = self.bind_as(conn)
        with patch:
            identity = ldap_auth.authenticate("AT\\ivanov", "secret")
        self.assertEqual(calls, ["ivanov@at.urfu.ru"])
        self.assertEqual(identity.role, UserRole.admin)
        self.assertEqual(identity.username, "ivanov")
        self.assertEqual(identity.guid, GUID)
        self.assertEqual(identity.email, "I.I.Ivanov@urfu.ru")
        self.assertTrue(conn.unbound)

    def test_viewer_group_gives_viewer(self):
        patch, _ = self.bind_as(FakeConn(groups=[VIEWERS]))
        with patch:
            self.assertEqual(ldap_auth.authenticate("ivanov", "secret").role, UserRole.viewer)

    def test_member_of_no_group_is_denied(self):
        patch, _ = self.bind_as(FakeConn(groups=[]))
        with patch, self.assertRaisesRegex(ldap_auth.LdapDenied, "групп"):
            ldap_auth.authenticate("ivanov", "secret")

    def test_disabled_account_is_denied(self):
        patch, _ = self.bind_as(FakeConn(groups=[ADMINS], disabled=True))
        with patch, self.assertRaises(ldap_auth.LdapDenied):
            ldap_auth.authenticate("ivanov", "secret")

    def test_wrong_password_is_denied(self):
        patch, _ = self.bind_as(FakeConn(groups=[ADMINS]))
        with patch, self.assertRaisesRegex(ldap_auth.LdapDenied, "Неверный логин"):
            ldap_auth.authenticate("ivanov", "wrong")

    def test_empty_password_never_reaches_the_domain(self):
        # AD считает bind с пустым паролем анонимным и «успешным»
        patch, calls = self.bind_as(FakeConn(groups=[ADMINS]), password="")
        with patch, self.assertRaises(ldap_auth.LdapDenied):
            ldap_auth.authenticate("ivanov", "")
        self.assertEqual(calls, [])

    def test_no_role_groups_configured_closes_domain_login(self):
        patch, calls = self.bind_as(FakeConn(groups=[ADMINS]))
        with mock.patch.multiple(settings, ldap_admin_groups="", ldap_viewer_groups=""), patch:
            with self.assertRaisesRegex(ldap_auth.LdapDenied, "не заданы группы"):
                ldap_auth.authenticate("ivanov", "secret")
        self.assertEqual(calls, [])

    def test_service_account_finds_dn_then_binds_as_user(self):
        conn = FakeConn(groups=[ADMINS])
        with mock.patch.multiple(settings, ldap_bind_dn="CN=svc-fleet,DC=at,DC=urfu,DC=ru", ldap_bind_password="secret"):
            patch, calls = self.bind_as(conn)
            with patch:
                identity = ldap_auth.authenticate("ivanov", "secret")
            self.assertEqual(calls, ["CN=svc-fleet,DC=at,DC=urfu,DC=ru", USER_DN])
            self.assertEqual(identity.role, UserRole.admin)

            with mock.patch.object(ldap_auth, "_bind", side_effect=lambda u, p, t=None: conn if u.startswith("CN=svc") else None):
                with self.assertRaisesRegex(ldap_auth.LdapDenied, "Неверный логин"):
                    ldap_auth.authenticate("ivanov", "wrong")

    def test_recheck_searches_by_binary_guid(self):
        conn = FakeConn(groups=[VIEWERS])
        with mock.patch.multiple(settings, ldap_bind_dn="CN=svc-fleet,DC=at,DC=urfu,DC=ru", ldap_bind_password="secret"):
            patch, _ = self.bind_as(conn)
            with patch:
                identity = ldap_auth.recheck(GUID)
        expected = "(objectGUID=" + "".join(f"\\{b:02x}" for b in uuid.UUID(GUID).bytes_le) + ")"
        self.assertEqual(conn.filters[0], expected)
        self.assertEqual(identity.role, UserRole.viewer)

    def test_recheck_of_account_removed_from_groups(self):
        with mock.patch.multiple(settings, ldap_bind_dn="CN=svc-fleet,DC=at,DC=urfu,DC=ru", ldap_bind_password="secret"):
            patch, _ = self.bind_as(FakeConn(groups=[]))
            with patch:
                self.assertIsNone(ldap_auth.recheck(GUID))

    def test_raw_guid_bytes_as_returned_without_schema(self):
        conn = FakeConn(groups=[ADMINS])
        conn.attrs["objectGUID"] = [uuid.UUID(GUID).bytes_le]
        conn.attrs["userAccountControl"] = ["512"]
        patch, _ = self.bind_as(conn)
        with patch:
            self.assertEqual(ldap_auth.authenticate("ivanov", "secret").guid, GUID)

    def test_draft_settings_apply_only_inside_use(self):
        draft = ldap_config.LdapConfig(enabled=True, url="ldaps://dc", domain="example.org", base_dn="DC=example,DC=org",
                                       operator_groups=[VIEWERS])
        with ldap_config.use(draft):
            self.assertEqual(ldap_auth.login_matches("ivanov@example.org")[0][0], "логин Windows")
            self.assertEqual(dict(ldap_auth.role_groups())[UserRole.operator], [VIEWERS])
        self.assertEqual(ldap_auth.login_matches("ivanov@example.org")[0][0], "UPN или почта")

    def test_diagnose_reports_groups_and_user_role(self):
        conn = FakeConn(groups=[VIEWERS])
        conn_search = conn.search

        def search(base, search_filter, scope, attributes=None, size_limit=0):
            if search_filter == "(objectClass=group)":
                conn.entries = [FakeEntry(base, {})] if base == VIEWERS else []
                return bool(conn.entries)
            if search_filter.startswith("(&") and "memberOf:" in search_filter:
                conn.entries = [FakeEntry(USER_DN, {})] * 3
                return True
            return conn_search(base, search_filter, scope, attributes, size_limit)

        conn.search = search
        with mock.patch.multiple(settings, ldap_bind_dn="CN=svc-fleet,DC=at,DC=urfu,DC=ru", ldap_bind_password="secret"):
            patch, _ = self.bind_as(conn)
            with patch:
                report = ldap_auth.diagnose(r"AT\ivanov")
        self.assertEqual(report["bind"], "ok")
        self.assertEqual([(g["dn"], g["found"], g["members"]) for g in report["groups"]], [(ADMINS, False, None), (VIEWERS, True, 3)])
        self.assertEqual(report["user"], {"username": "ivanov", "found": True, "matched_by": "логин Windows", "display_name": "Иванов Иван", "role": "viewer"})

    def test_service_account_required_for_group_search(self):
        with self.assertRaisesRegex(ldap_auth.LdapUnavailable, "служебная"):
            ldap_auth.search_groups("OOD")

    def test_group_dn_is_escaped_in_the_filter(self):
        group = "CN=FM (admins),OU=Groups,DC=at,DC=urfu,DC=ru"
        conn = FakeConn()
        with mock.patch.object(settings, "ldap_admin_groups", group):
            ldap_auth._role(conn, USER_DN)
        self.assertIn(r"CN=FM \28admins\29", conn.filters[0])


class ManualRoleTests(unittest.TestCase):
    def user(self):
        from models.user import User

        return User(username="ivanov", role=UserRole.operator, ldap_role=UserRole.operator, role_override=None)

    def test_group_role_applies_without_manual_role(self):
        from services.ldap_users import apply_role

        user = self.user()
        self.assertTrue(apply_role(user, UserRole.viewer))
        self.assertEqual((user.role, user.ldap_role), (UserRole.viewer, UserRole.viewer))
        self.assertFalse(apply_role(user, UserRole.viewer))

    def test_manual_promotion_survives_group_sync(self):
        from services.ldap_users import apply_role, set_manual_role

        user = self.user()
        set_manual_role(user, UserRole.admin)
        apply_role(user, UserRole.operator)
        self.assertEqual((user.role, user.role_override), (UserRole.admin, UserRole.admin))

    def test_choosing_the_group_role_returns_role_to_groups(self):
        from services.ldap_users import apply_role, set_manual_role

        user = self.user()
        set_manual_role(user, UserRole.admin)
        set_manual_role(user, UserRole.operator)
        self.assertIsNone(user.role_override)
        apply_role(user, UserRole.viewer)
        self.assertEqual(user.role, UserRole.viewer)


class LdapSettingsSchemaTests(unittest.TestCase):
    def payload(self, **kw):
        from routers.ldap_settings import LdapSettingsIn

        base = dict(enabled=True, url="ldaps://at.urfu.ru", domain="at.urfu.ru", base_dn="DC=at,DC=urfu,DC=ru")
        return LdapSettingsIn(**{**base, **kw})

    def test_groups_are_trimmed_and_deduplicated(self):
        p = self.payload(operator_groups=[f" {ADMINS} ", ADMINS.lower(), "", VIEWERS])
        self.assertEqual(p.operator_groups, [ADMINS, VIEWERS])

    def test_rejects_non_dn_group_and_non_ldap_url(self):
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            self.payload(admin_groups=["IRITRTF OOD Staff"])
        with self.assertRaises(ValidationError):
            self.payload(url="https://at.urfu.ru")
        self.assertEqual(self.payload(url="ldaps://a, ldaps://b,").url, "ldaps://a, ldaps://b")

    def test_password_none_means_keep(self):
        self.assertIsNone(self.payload().bind_password)
        self.assertEqual(self.payload(bind_password="").bind_password, "")


if __name__ == "__main__":
    unittest.main()
