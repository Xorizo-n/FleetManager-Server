import unittest

from models.task import TaskType
from models.user import UserRole
from services.task_visibility import can_view_task_type


class TaskVisibilityTests(unittest.TestCase):
    def test_viewer_cannot_view_diagnostic_tasks(self):
        self.assertFalse(can_view_task_type(UserRole.viewer, TaskType.host_diagnostic))

    def test_editor_can_view_diagnostic_tasks(self):
        self.assertTrue(can_view_task_type(UserRole.operator, TaskType.host_diagnostic))

    def test_viewer_can_view_regular_tasks(self):
        self.assertTrue(can_view_task_type(UserRole.viewer, TaskType.playbook))


if __name__ == "__main__":
    unittest.main()
