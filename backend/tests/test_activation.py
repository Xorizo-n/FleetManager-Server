import unittest
import uuid

from pydantic import ValidationError

from models.host import Host
from schemas.agent import AgentHeartbeatRequest
from schemas.host import HostOut
from services.activation import EXPIRING, GRACE, LICENSED, UNLICENSED, activation_state, product_state

# Heartbeat агента 2026.10.17 с SU5-K104-W09: Windows в режиме уведомлений, Office 2019 KMS
# в пробном периоде, Project — заглушка Retail(Grace); порт KMS с подсети SU5 закрыт.
SU5_ACTIVATION = {
    "collected_at": "2026-10-17T10:20:00Z",
    "client_machine_id": "36185d39-f35d-4efb-8610-c2aac5b98cb4",
    "kms_probe": {"host": "sk5-cod-kms3.at.urfu.ru", "port": 1688, "reachable": False, "error": "TimedOut"},
    "products": [
        {"kind": "windows", "id": "3f1afc82-f8ac-4f6c-8005-1d233e606eee", "name": "Windows(R), ProfessionalEducation edition",
         "description": "Windows(R) Operating System, VOLUME_KMSCLIENT channel", "channel": "Volume:GVLK", "partial_product_key": "J447Y",
         "license_status": 5, "status_reason": 0xC004F00F, "grace_minutes": 0, "kms_machine": None, "kms_port": 1688,
         "discovered_kms_machine": "sk5-cod-kms3.at.urfu.ru", "discovered_kms_port": 1688,
         "last_request": {"at": "2026-10-17T06:56:00Z", "kms": "sk5-cod-kms3.at.urfu.ru:1688", "result": "0xC0020017"}},
        {"kind": "office", "id": "aaaa", "name": "Office 19, Office19ProjectPro2019R_Grace edition", "description": "Office 19, RETAIL(Grace) channel",
         "channel": "Retail", "partial_product_key": "B4JJJ", "license_status": 5, "status_reason": 0xC004F009, "grace_minutes": 0, "last_request": None},
        {"kind": "office", "id": "85dd8b5f-eaa4-4af3-a628-cce9e77c9a03", "name": "Office 19, Office19ProPlus2019VL_KMS_Client_AE edition",
         "description": "Office 19, VOLUME_KMSCLIENT channel", "channel": "Volume:GVLK", "partial_product_key": "6MWKP",
         "license_status": 2, "status_reason": 0x4004F00C, "grace_minutes": 38879},
    ],
}


def kms_product(status: int, grace_minutes: int, **extra) -> dict:
    return {"kind": "windows", "description": "Windows(R) Operating System, VOLUME_KMSCLIENT channel",
            "license_status": status, "grace_minutes": grace_minutes, **extra}


class ProductStateTests(unittest.TestCase):
    def test_kms_activation_is_licensed_while_it_renews(self):
        self.assertEqual(product_state(kms_product(1, 251882)), LICENSED)

    def test_kms_activation_close_to_expiry_means_renewal_fails(self):
        self.assertEqual(product_state(kms_product(1, 20 * 24 * 60)), EXPIRING)

    def test_retail_and_mak_licenses_have_no_expiry(self):
        self.assertEqual(product_state({"kind": "office", "channel": "MAK", "license_status": 1, "grace_minutes": 0}), LICENSED)
        self.assertEqual(product_state({"kind": "windows", "channel": "Retail", "license_status": 1, "grace_minutes": 100}), LICENSED)

    def test_grace_and_notification(self):
        for status in (2, 3, 4, 6):
            self.assertEqual(product_state(kms_product(status, 38879)), GRACE)
        self.assertEqual(product_state(kms_product(5, 0)), UNLICENSED)
        self.assertEqual(product_state(kms_product(0, 0)), UNLICENSED)


class ActivationStateTests(unittest.TestCase):
    def test_worst_product_of_each_kind(self):
        self.assertEqual(activation_state(SU5_ACTIVATION, "windows"), UNLICENSED)
        # ProPlus в пробном периоде, но Project не активирован совсем
        self.assertEqual(activation_state(SU5_ACTIVATION, "office"), UNLICENSED)

    def test_missing_data_and_missing_products(self):
        self.assertIsNone(activation_state(None, "windows"))
        self.assertIsNone(activation_state({"products": [kms_product(1, 251882)]}, "office"))


class ActivationHeartbeatTests(unittest.TestCase):
    def test_heartbeat_carries_the_activation_snapshot(self):
        payload = AgentHeartbeatRequest(machine_id=str(uuid.uuid4()), os="windows_11", activation=SU5_ACTIVATION)

        stored = payload.activation.model_dump(mode="json")
        self.assertFalse(stored["kms_probe"]["reachable"])
        self.assertEqual(stored["products"][0]["status_reason"], 0xC004F00F)
        self.assertEqual(stored["products"][0]["last_request"]["result"], "0xC0020017")
        self.assertIsNone(stored["products"][1]["last_request"])
        self.assertEqual(activation_state(stored, "windows"), UNLICENSED)

    def test_old_agents_send_no_activation(self):
        self.assertIsNone(AgentHeartbeatRequest(machine_id=str(uuid.uuid4()), os="windows_10").activation)

    def test_unknown_product_kinds_are_rejected(self):
        with self.assertRaises(ValidationError):
            AgentHeartbeatRequest(machine_id=str(uuid.uuid4()), os="windows_11",
                                  activation={"products": [{"kind": "visio", "license_status": 1}]})

    def test_host_out_exposes_the_summary(self):
        host = Host(id=uuid.uuid4(), hostname="SU5-K104-W09", os="windows_11", status="online", license_activation=SU5_ACTIVATION)
        host.created_at = host.updated_at = __import__("datetime").datetime(2026, 10, 17)
        out = HostOut.model_validate(host)
        self.assertEqual(out.activation_windows, UNLICENSED)
        self.assertEqual(out.activation_office, UNLICENSED)
        self.assertEqual(out.license_activation["client_machine_id"], "36185d39-f35d-4efb-8610-c2aac5b98cb4")


if __name__ == "__main__":
    unittest.main()
