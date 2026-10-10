import unittest
import uuid
from types import SimpleNamespace

from models.host import Host
from schemas.agent import AgentAlertRequest, AgentHardware
from services.hardware_change import hardware_changes

GIB = 1024 ** 3
VERSION = "2026.10.10.10"


def stored(**overrides):
    values = dict(
        hw_manufacturer="Micro-Star International Co., Ltd.",
        hw_model="Modern ADL-P AM272 (MS-AF82)",
        hw_serial_number="MSAF82MAS0103613",
        hw_os_caption="Microsoft Windows 11 Enterprise",
        hw_processor="12th Gen Intel(R) Core(TM) i7-1260P",
        hw_total_memory_bytes=16949366784,
        hw_agent_version=VERSION,
    )
    values.update(overrides)
    return Host(id=uuid.uuid4(), **values)


def reported(**overrides):
    values = dict(
        manufacturer="Micro-Star International Co., Ltd.",
        model="Modern ADL-P AM272 (MS-AF82)",
        serial_number="MSAF82MAS0103613",
        operating_system="Microsoft Windows 11 Enterprise",
        processor="12th Gen Intel(R) Core(TM) i7-1260P",
        total_memory_bytes=16949366784,
    )
    values.update(overrides)
    return AgentHardware(**values)


class HardwareChangeTests(unittest.TestCase):
    def test_same_hardware_is_no_change(self):
        self.assertEqual(hardware_changes(stored(), reported(), VERSION), [])

    def test_memory_change_is_named_in_gigabytes(self):
        self.assertEqual(hardware_changes(stored(), reported(total_memory_bytes=8 * GIB), VERSION), ["Память: 16 ГБ → 8 ГБ"])

    def test_small_memory_fluctuation_is_ignored(self):
        self.assertEqual(hardware_changes(stored(), reported(total_memory_bytes=16949366784 - 64 * 1024 ** 2), VERSION), [])

    def test_several_parts_are_listed(self):
        changes = hardware_changes(stored(), reported(model="B760 Pro RS/D4", serial_number="NEW123", manufacturer="ASRock"), VERSION)
        self.assertEqual(changes, [
            "Производитель: Micro-Star International Co., Ltd. → ASRock",
            "Модель: Modern ADL-P AM272 (MS-AF82) → B760 Pro RS/D4",
            "Серийный номер: MSAF82MAS0103613 → NEW123",
        ])

    def test_os_name_language_is_not_a_hardware_change(self):
        self.assertEqual(hardware_changes(stored(), reported(operating_system="Майкрософт Windows 11 Корпоративная"), VERSION), [])

    def test_unknown_values_are_not_compared(self):
        self.assertEqual(hardware_changes(stored(hw_serial_number=None), reported(serial_number="X"), VERSION), [])
        self.assertEqual(hardware_changes(stored(), reported(processor=None), VERSION), [])

    def test_only_reports_of_the_same_agent_version_are_compared(self):
        # Скриптовый агент писал модель диска в серийный номер
        old = stored(hw_serial_number="WD PC SN560 SDDPNQE-512G-1032 (477 GB)", hw_agent_version=None)
        self.assertEqual(hardware_changes(old, reported(), VERSION), [])
        self.assertEqual(hardware_changes(stored(hw_agent_version="2026.10.10.9"), reported(total_memory_bytes=8 * GIB), VERSION), [])
        self.assertEqual(hardware_changes(stored(), reported(total_memory_bytes=8 * GIB), None), [])


class _Db:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        pass

    def refresh(self, obj):
        pass


class AgentAlertEndpointTests(unittest.TestCase):
    def _post(self, alert_type):
        from routers.agent import create_alert

        machine_id = uuid.uuid4()
        host = SimpleNamespace(id=uuid.uuid4(), agent_id=machine_id, hardware_fingerprint="old")
        payload = AgentAlertRequest(machine_id=machine_id, alert_type=alert_type, message="Hardware fingerprint changed.",
                                    previous_fingerprint="A", current_fingerprint="B")
        db = _Db()
        return create_alert(payload, host=host, db=db), db, host

    def test_agent_hardware_alert_is_accepted_but_not_stored(self):
        alert, db, host = self._post("hardware_changed")
        self.assertEqual(db.added, [])
        self.assertIsNotNone(alert.id)
        self.assertEqual(host.hardware_fingerprint, "old")

    def test_other_alert_types_are_stored(self):
        alert, db, _ = self._post("disk_failure")
        self.assertEqual(db.added, [alert])


if __name__ == "__main__":
    unittest.main()
