import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from models.host import Host, HostStatus
from routers.agent import register_agent
from schemas.agent import AgentRegisterRequest


def _result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


class RegisterAttachesExistingHostTests(unittest.TestCase):
    """Хост уже есть в реестре без агента (заведён вручную или агент снят): регистрация привязывает его."""

    def test_host_found_by_name_gets_the_new_agent_id(self):
        machine_id = str(uuid.uuid4())
        host = Host(id=uuid.uuid4(), hostname="SU5-VM-SBX", ip_address="10.40.241.62", agent_id=None,
                    status=HostStatus.offline, credential_id=uuid.uuid4(), is_agent_managed=True)
        enrollment = SimpleNamespace(is_active=True, expires_at=None)
        credential = SimpleNamespace(is_agent_managed=True, public_key="ssh-ed25519 AAAA", login=r"at\admin")
        db = MagicMock()
        # токен регистрации → поиск по machine-id (нет) → поиск по имени (есть)
        db.execute.side_effect = [_result(enrollment), _result(None), _result(host)]
        db.get.return_value = credential
        payload = AgentRegisterRequest(enrollment_token="enrollment-secret-12345", machine_id=machine_id,
                                       hostname="SU5-VM-SBX", ip_address="10.40.241.62", os="windows_11")

        with patch("routers.agent.apply_auto_group"):
            response = register_agent(payload, MagicMock(), db)

        self.assertEqual(str(host.agent_id), machine_id)
        self.assertEqual(str(response.agent_id), machine_id)
        self.assertEqual(response.host_id, host.id)
        self.assertEqual(response.ssh_public_key, "ssh-ed25519 AAAA")
        self.assertEqual(host.status, HostStatus.online)


if __name__ == "__main__":
    unittest.main()
