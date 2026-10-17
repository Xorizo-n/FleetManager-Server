import copy
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from models.agent import AgentAlert, HardwareEvent
from models.host import Host
from routers.agent import _record_hardware_changes
from schemas.agent import AgentHeartbeatRequest
from services.workplace_devices import (
    ADDED,
    CHANGED,
    REMOVED,
    apply_components,
    compare_internal,
    describe,
    peripheral_items,
    pending_devices,
    update_peripherals,
)

T0 = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)

# Снимок агента с SU5-K104-W09
SU5 = {
    "baseboard": {"manufacturer": "Micro-Star International Co., Ltd.", "product": "PRO B760M-A DDR4 II (MS-7D99)", "serial_number": None},
    "bios_version": "1.F1",
    "memory_modules": [{"slot": "Controller1-DIMMB2", "manufacturer": "0x0080", "part_number": None, "serial_number": "01480300",
                        "capacity_bytes": 17179869184, "speed_mhz": 3200}],
    "physical_disks": [{"model": "AirDisk 512GB SSD", "serial_number": "0000_0006_2501_2623_3A5A_2703_4E00_0041", "bus_type": "NVMe", "size_bytes": 512105932800},
                       {"model": "TOSHIBA DT02ABA200V", "serial_number": "35F2S4R1SNDL", "bus_type": "IDE", "size_bytes": 2000396321280}],
    "gpus": [{"name": "Intel(R) UHD Graphics 770", "driver_version": "32.0.101.7088", "pnp_id": "PCI\\VEN_8086&DEV_4680&SUBSYS_7D991462&REV_0C\\3&11583659&0&10"}],
    "monitors": [{"manufacturer": "AUS", "model": "VA27UQSB", "serial_number": "S2LMTF164672", "product_code": "27C7", "year": 2023, "connection": 5}],
    "input_devices": [{"kind": "keyboard", "name": "USB Keyboard", "vid": "1A2C", "pid": "2124", "serial": None, "device_class": None},
                      {"kind": "mouse", "name": "Usb Mouse", "vid": "1C4F", "pid": "0034", "serial": None, "device_class": None}],
    "usb_devices": [{"kind": "usb", "name": "Usb Mouse", "vid": "1C4F", "pid": "0034", "serial": None, "device_class": "HIDClass"},
                    {"kind": "usb", "name": "USB Keyboard", "vid": "1A2C", "pid": "2124", "serial": None, "device_class": "USB"},
                    {"kind": "usb", "name": "Logitech USB Headset", "vid": "046D", "pid": "0A45", "serial": None, "device_class": "USB"}],
}


def snapshot(**changes):
    result = copy.deepcopy(SU5)
    result.update(changes)
    return result


def without_mouse():
    return snapshot(
        input_devices=[d for d in SU5["input_devices"] if d["kind"] != "mouse"],
        usb_devices=[d for d in SU5["usb_devices"] if d["pid"] != "0034"],
    )


class InternalComponentTests(unittest.TestCase):
    def test_no_changes(self):
        self.assertEqual(compare_internal(SU5, snapshot()), [])

    def test_memory_module_removed_and_replaced(self):
        removed = compare_internal(SU5, snapshot(memory_modules=[]))
        # Пустой список — сбой WMI, а не вынутая память
        self.assertEqual(removed, [])

        replaced = snapshot(memory_modules=[dict(SU5["memory_modules"][0], serial_number="99999999", capacity_bytes=8589934592)])
        [change] = compare_internal(SU5, replaced)
        self.assertEqual((change.category, change.action, change.alert_type), ("memory", CHANGED, "hardware_changed"))
        self.assertIn("16 ГБ", change.summary)
        self.assertIn("8 ГБ", change.summary)

    def test_disk_swap_is_a_removal_and_an_addition(self):
        new_disk = {"model": "Samsung SSD 870 EVO 1TB", "serial_number": "S6PNNM0T", "bus_type": "IDE", "size_bytes": 1000204886016}
        changes = compare_internal(SU5, snapshot(physical_disks=[SU5["physical_disks"][0], new_disk]))
        self.assertEqual(sorted((c.action, c.category) for c in changes), [(ADDED, "disk"), (REMOVED, "disk")])
        self.assertTrue(all(c.alert_type == "hardware_changed" for c in changes))
        self.assertIn("Пропал диск: TOSHIBA DT02ABA200V 2 ТБ (с/н 35F2S4R1SNDL)".replace("2 ТБ", "1,8 ТБ"), [c.summary for c in changes])

    def test_gpu_driver_rename_is_not_a_change(self):
        renamed = snapshot(gpus=[dict(SU5["gpus"][0], name="Intel(R) UHD Graphics", driver_version="33.0")])
        self.assertEqual(compare_internal(SU5, renamed), [])

    def test_bios_update_is_logged_without_alert(self):
        [change] = compare_internal(SU5, snapshot(bios_version="1.F2"))
        self.assertEqual(change.summary, "BIOS: 1.F1 → 1.F2")
        self.assertIsNone(change.alert_type)


class PeripheralTests(unittest.TestCase):
    def test_usb_list_does_not_repeat_keyboard_and_mouse(self):
        items = peripheral_items(SU5)
        self.assertEqual(sorted(c for c, _ in items.values()), ["keyboard", "monitor", "mouse", "usb"])

    def test_identical_devices_are_counted(self):
        two_mice = snapshot(input_devices=SU5["input_devices"] + [SU5["input_devices"][1]])
        self.assertEqual(sum(1 for c, _ in peripheral_items(two_mice).values() if c == "mouse"), 2)

    def test_first_snapshot_is_the_baseline(self):
        state, changes = update_peripherals(None, SU5, T0)
        self.assertEqual(changes, [])
        self.assertTrue(all(e["present"] and e["since"] is None for e in state.values()))

    def test_short_unplug_is_not_logged(self):
        state, _ = update_peripherals(None, SU5, T0)
        state, changes = update_peripherals(state, without_mouse(), T0 + timedelta(minutes=5))
        self.assertEqual(changes, [])
        self.assertEqual([(p["category"], p["missing"]) for p in pending_devices(state)], [("mouse", True)])
        state, changes = update_peripherals(state, SU5, T0 + timedelta(minutes=10))
        self.assertEqual(changes, [])
        self.assertEqual(pending_devices(state), [])

    def test_mouse_missing_for_half_an_hour_raises_an_alert(self):
        state, _ = update_peripherals(None, SU5, T0)
        state, _ = update_peripherals(state, without_mouse(), T0 + timedelta(minutes=5))
        state, changes = update_peripherals(state, without_mouse(), T0 + timedelta(minutes=20))
        self.assertEqual(changes, [])
        state, changes = update_peripherals(state, without_mouse(), T0 + timedelta(minutes=35))
        [change] = changes
        self.assertEqual((change.category, change.action, change.alert_type), ("mouse", REMOVED, "device_missing"))
        self.assertEqual(change.summary, "Пропала мышь: Usb Mouse (1C4F:0034)")
        self.assertNotIn("mouse", [e["category"] for e in state.values()])
        # Вернули — тоже через полчаса, без алерта
        state, _ = update_peripherals(state, SU5, T0 + timedelta(minutes=40))
        state, changes = update_peripherals(state, SU5, T0 + timedelta(minutes=75))
        self.assertEqual([(c.category, c.action, c.alert_type) for c in changes], [("mouse", ADDED, None)])

    def test_new_usb_device_is_logged_without_alert(self):
        flash_camera = snapshot(usb_devices=SU5["usb_devices"] + [{"kind": "usb", "name": "FHD Camera", "vid": "5986", "pid": "213A", "serial": "01.00.00"}])
        state, _ = update_peripherals(None, SU5, T0)
        state, _ = update_peripherals(state, flash_camera, T0 + timedelta(minutes=5))
        state, changes = update_peripherals(state, flash_camera, T0 + timedelta(minutes=40))
        self.assertEqual([(c.summary, c.alert_type) for c in changes], [("Появилось USB-устройство: FHD Camera (5986:213A) (с/н 01.00.00)", None)])

    def test_monitor_description(self):
        self.assertEqual(describe("monitor", SU5["monitors"][0]), "AUS VA27UQSB (с/н S2LMTF164672)")


class ApplyComponentsTests(unittest.TestCase):
    def host(self):
        return Host(id=uuid.uuid4(), hostname="SU5-K104-W09", os="windows_11", status="online")

    def test_old_agents_leave_everything_as_is(self):
        host = self.host()
        self.assertEqual(apply_components(host, None, T0, same_agent_version=True), [])
        self.assertIsNone(host.hw_components)

    def test_agent_update_rebaselines_instead_of_comparing(self):
        host = self.host()
        apply_components(host, SU5, T0, same_agent_version=True)
        changes = apply_components(host, snapshot(bios_version="1.F2", input_devices=[]), T0 + timedelta(hours=1), same_agent_version=False)
        self.assertEqual(changes, [])
        self.assertEqual(host.hw_components["bios_version"], "1.F2")

    def test_changes_are_reported_for_the_same_agent(self):
        host = self.host()
        apply_components(host, SU5, T0, same_agent_version=True)
        changes = apply_components(host, snapshot(bios_version="1.F2"), T0 + timedelta(minutes=5), same_agent_version=True)
        self.assertEqual([c.category for c in changes], ["bios"])


class RecordChangesTests(unittest.TestCase):
    class FakeDb:
        def __init__(self):
            self.added = []

        def add(self, obj):
            self.added.append(obj)

    def test_events_and_grouped_alerts(self):
        host = Host(id=uuid.uuid4(), hostname="SU5-K104-W09", os="windows_11", status="online", hardware_fingerprint="old")
        apply_components(host, SU5, T0, same_agent_version=True)
        state, _ = update_peripherals(host.hw_device_state, without_mouse(), T0 + timedelta(minutes=5))
        _, mouse = update_peripherals(state, without_mouse(), T0 + timedelta(minutes=40))
        memory = compare_internal(SU5, snapshot(memory_modules=[dict(SU5["memory_modules"][0], serial_number="1")]))
        db = self.FakeDb()

        _record_hardware_changes(db, host, ["Память: 16 ГБ → 8 ГБ"], memory + mouse, "new", T0)

        events = [o for o in db.added if isinstance(o, HardwareEvent)]
        alerts = {o.alert_type: o for o in db.added if isinstance(o, AgentAlert)}
        self.assertEqual([e.category for e in events], ["system", "memory", "mouse"])
        self.assertEqual(alerts["hardware_changed"].message.split("; ")[0], "Память: 16 ГБ → 8 ГБ")
        self.assertEqual(alerts["hardware_changed"].current_fingerprint, "new")
        self.assertEqual(alerts["device_missing"].message, "Пропала мышь: Usb Mouse (1C4F:0034)")
        self.assertEqual(host.hw_changed_at, T0)


class HeartbeatSchemaTests(unittest.TestCase):
    def test_heartbeat_carries_components(self):
        payload = AgentHeartbeatRequest(machine_id=str(uuid.uuid4()), os="windows_11", hardware={"components": SU5})
        dumped = payload.hardware.components.model_dump(mode="json")
        self.assertEqual(dumped["monitors"][0]["model"], "VA27UQSB")
        self.assertEqual(dumped["input_devices"][1]["kind"], "mouse")

    def test_old_agents_send_no_components(self):
        self.assertIsNone(AgentHeartbeatRequest(machine_id=str(uuid.uuid4()), os="windows_10").hardware.components)


if __name__ == "__main__":
    unittest.main()
