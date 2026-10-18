import unittest
import uuid
from unittest import mock

from config import settings
from models.user import UserRole
from services import ldap_auth

ADMINS = "CN=FM-Admins,OU=Groups,DC=at,DC=urfu,DC=ru"
VIEWERS = "CN=FM-Viewers,OU=Groups,DC=at,DC=urfu,DC=ru"
USER_DN = "CN=Иванов Иван,OU=Staff,DC=at,DC=urfu,DC=ru"
GUID = str(uuid.uuid4())


class FakeEntry:
    def __init__(self, dn, attrs):
        self.entry_dn = dn
        self.entry_attributes_as_dict = attrs


class FakeConn:
    """Каталог из одной записи: фильтр по sAMAccountName/objectGUID и проверка членства в группах."""

    def __init__(self, groups=(), disabled=False):
        self.groups = set(groups)
        self.attrs = {
            "sAMAccountName": ["ivanov"],
            "mail": ["I.I.Ivanov@urfu.ru"],
            "userPrincipalName": ["ivanov@at.urfu.ru"],
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
        elif "sAMAccountName=ivanov)" in search_filter or search_filter.startswith("(objectGUID="):
            self.entries = [FakeEntry(USER_DN, self.attrs)]
        return bool(self.entries)

    def unbind(self):
        self.unbound = True


class LdapAuthTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.multiple(settings, ldap_enabled=True, ldap_domain="at.urfu.ru", ldap_bind_dn="",
                                      ldap_bind_password="", ldap_admin_groups=ADMINS, ldap_operator_groups="",
                                      ldap_viewer_groups=VIEWERS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def bind_as(self, conn, password="secret"):
        """Подменяет bind: верный пароль у ivanov и у служебной записи, остальное — неверный пароль."""
        calls = []

        def fake_bind(user, pwd):
            calls.append(user)
            return conn if pwd == password else None

        return mock.patch.object(ldap_auth, "_bind", side_effect=fake_bind), calls

    def test_split_login_accepts_domain_forms(self):
        self.assertEqual(ldap_auth.split_login("ivanov"), "ivanov")
        self.assertEqual(ldap_auth.split_login(r"AT\ivanov"), "ivanov")
        self.assertEqual(ldap_auth.split_login("ivanov@AT.urfu.ru"), "ivanov")
        self.assertEqual(ldap_auth.split_login(" i.i.ivanov "), "i.i.ivanov")

    def test_split_login_rejects_other_domain_and_filter_syntax(self):
        self.assertIsNone(ldap_auth.split_login("ivanov@gmail.com"))
        self.assertIsNone(ldap_auth.split_login("*)(objectClass=*"))
        self.assertIsNone(ldap_auth.split_login(""))

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

            with mock.patch.object(ldap_auth, "_bind", side_effect=lambda u, p: conn if u.startswith("CN=svc") else None):
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


if __name__ == "__main__":
    unittest.main()
