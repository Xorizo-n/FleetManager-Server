import unittest

from services.disk_alerts import check_disks, used_percent

GB = 1024 ** 3


def disk(name, size_gb, free_gb):
    return {"name": name, "size_bytes": int(size_gb * GB), "free_bytes": int(free_gb * GB)}


class DiskAlertTests(unittest.TestCase):
    def test_used_percent_rounds_like_the_ui(self):
        self.assertEqual(used_percent(disk("C:", 100, 10.4)), 90)
        self.assertEqual(used_percent(disk("C:", 100, 10.6)), 89)
        self.assertIsNone(used_percent(disk("C:", 0, 0)))

    def test_alert_once_when_crossing_the_threshold(self):
        first = check_disks([disk("C:", 119, 8.2), disk("D:", 500, 300)], None)
        self.assertEqual(first.alarmed, ["C:"])
        self.assertEqual(first.messages, ["Диск C: заполнен на 93%: свободно 8,2 ГБ из 119 ГБ"])
        again = check_disks([disk("C:", 119, 7.0)], first.alarmed)
        self.assertEqual((again.alarmed, again.messages), (["C:"], []))

    def test_hysteresis_rearms_only_below_clear_threshold(self):
        # 88% — ещё в тревоге, повторного алерта нет
        hovering = check_disks([disk("C:", 100, 12)], ["C:"])
        self.assertEqual((hovering.alarmed, hovering.messages), (["C:"], []))
        # 80% — освободился, тревога снята; следующее переполнение — новый алерт
        cleared = check_disks([disk("C:", 100, 20)], hovering.alarmed)
        self.assertEqual(cleared.alarmed, [])
        self.assertEqual(len(check_disks([disk("C:", 100, 5)], cleared.alarmed).messages), 1)

    def test_several_disks_and_removed_disk(self):
        result = check_disks([disk("C:", 100, 5), disk("f:", 16, 0.1)], ["E:"])
        self.assertEqual(result.alarmed, ["C:", "F:"])
        self.assertEqual(len(result.messages), 2)


if __name__ == "__main__":
    unittest.main()
