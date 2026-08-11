import unittest
import uuid
from datetime import datetime, timezone

from models.task import TaskType, TaskStatus
from schemas.task import TaskRunOut


class HostDiagnosticSchemaTests(unittest.TestCase):
    def test_task_type_has_host_diagnostic(self):
        self.assertEqual(TaskType.host_diagnostic.value, "host_diagnostic")

    def test_task_output_accepts_diagnostic_type(self):
        result = TaskRunOut(
            id=uuid.uuid4(),
            task_type=TaskType.host_diagnostic,
            playbook_name=None,
            host_ids=[str(uuid.uuid4())],
            status=TaskStatus.queued,
            created_at=datetime.now(timezone.utc),
            started_at=None,
            finished_at=None,
        )
        self.assertEqual(result.task_type, TaskType.host_diagnostic)


if __name__ == "__main__":
    unittest.main()
