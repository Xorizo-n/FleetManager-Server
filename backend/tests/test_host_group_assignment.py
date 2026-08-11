import unittest
import uuid

from pydantic import ValidationError

from schemas.host import HostGroupAssignRequest


class HostGroupAssignmentTests(unittest.TestCase):
    def test_existing_group_assignment_requires_hosts(self):
        group_id = uuid.uuid4()
        payload = HostGroupAssignRequest(host_ids=[uuid.uuid4()], group_id=group_id)
        self.assertEqual(payload.group_id, group_id)
        self.assertIsNone(payload.group_name)

    def test_new_group_assignment_accepts_name(self):
        payload = HostGroupAssignRequest(host_ids=[uuid.uuid4()], group_name="Рабочие станции")
        self.assertEqual(payload.group_name, "Рабочие станции")

    def test_assignment_rejects_missing_destination(self):
        with self.assertRaises(ValidationError):
            HostGroupAssignRequest(host_ids=[uuid.uuid4()])


if __name__ == "__main__":
    unittest.main()
