import unittest
import uuid

from services.permissions import (
    can_access_playbooks,
    can_manage_users,
    validate_role_change,
    validate_user_delete,
)


class PermissionTests(unittest.TestCase):
    def test_only_admin_and_operator_can_access_playbooks(self):
        self.assertTrue(can_access_playbooks("admin"))
        self.assertTrue(can_access_playbooks("operator"))
        self.assertFalse(can_access_playbooks("viewer"))

    def test_only_admin_can_manage_users(self):
        self.assertTrue(can_manage_users("admin"))
        self.assertFalse(can_manage_users("operator"))
        self.assertFalse(can_manage_users("viewer"))

    def test_admin_cannot_change_own_role(self):
        user_id = uuid.uuid4()
        with self.assertRaises(ValueError):
            validate_role_change("admin", user_id, user_id, "admin", "viewer", 2)

    def test_last_admin_cannot_be_demoted(self):
        with self.assertRaises(ValueError):
            validate_role_change("admin", uuid.uuid4(), uuid.uuid4(), "admin", "viewer", 1)

    def test_admin_can_change_another_users_role(self):
        validate_role_change("admin", uuid.uuid4(), uuid.uuid4(), "viewer", "operator", 1)

    def test_inactive_admin_can_be_demoted_without_losing_active_admin(self):
        validate_role_change("admin", uuid.uuid4(), uuid.uuid4(), "admin", "viewer", 1, False)


class UserDeleteTests(unittest.TestCase):
    def test_admin_deletes_another_user(self):
        validate_user_delete("admin", uuid.uuid4(), uuid.uuid4(), "operator", True, 1)
        validate_user_delete("admin", uuid.uuid4(), uuid.uuid4(), "admin", True, 2)

    def test_only_admin_deletes(self):
        with self.assertRaisesRegex(ValueError, "Только администратор"):
            validate_user_delete("operator", uuid.uuid4(), uuid.uuid4(), "viewer", True, 1)

    def test_own_account_cannot_be_deleted(self):
        me = uuid.uuid4()
        with self.assertRaisesRegex(ValueError, "собственную"):
            validate_user_delete("admin", me, me, "admin", True, 3)

    def test_last_active_admin_cannot_be_deleted(self):
        with self.assertRaisesRegex(ValueError, "последнего"):
            validate_user_delete("admin", uuid.uuid4(), uuid.uuid4(), "admin", True, 1)
        validate_user_delete("admin", uuid.uuid4(), uuid.uuid4(), "admin", False, 1)


if __name__ == "__main__":
    unittest.main()
