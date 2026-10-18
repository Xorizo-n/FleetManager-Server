import io
import unittest
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError

from models.host import Host, HostGroup
from models.wallpaper import DESKTOP, LOCK_SCREEN, Wallpaper, WallpaperAssignment
from schemas.agent import AgentHeartbeatRequest
from schemas.wallpaper import WallpaperAssignRequest
from services.wallpapers import WallpaperError, effective_wallpapers, inspect_image, wallpaper_target

SHA = "a" * 64


def image_bytes(fmt: str, size=(1920, 1080)) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", size, (30, 90, 160)).save(out, fmt)
    return out.getvalue()


def wallpaper(name: str) -> Wallpaper:
    return Wallpaper(id=uuid.uuid4(), name=name, file_name=f"{name}.jpg", content_type="image/jpeg", sha256=name.ljust(64, "0")[:64],
                     size_bytes=1, width=1, height=1, thumbnail=b"")


class InspectImageTests(unittest.TestCase):
    def test_png_and_jpeg_are_accepted_with_a_thumbnail(self):
        for fmt, content_type, ext in (("PNG", "image/png", ".png"), ("JPEG", "image/jpeg", ".jpg")):
            got_type, got_ext, width, height, thumbnail = inspect_image(image_bytes(fmt))
            self.assertEqual((got_type, got_ext, width, height), (content_type, ext, 1920, 1080))
            from PIL import Image

            with Image.open(io.BytesIO(thumbnail)) as thumb:
                self.assertEqual((thumb.format, thumb.width, thumb.height), ("JPEG", 320, 180))

    def test_small_images_are_not_upscaled(self):
        *_, thumbnail = inspect_image(image_bytes("PNG", (200, 100)))
        from PIL import Image

        with Image.open(io.BytesIO(thumbnail)) as thumb:
            self.assertEqual(thumb.size, (200, 100))

    def test_other_files_are_rejected(self):
        for data in (b"", b"not an image", image_bytes("GIF")):
            with self.assertRaises(WallpaperError):
                inspect_image(data)


class EffectiveWallpaperTests(unittest.TestCase):
    def setUp(self):
        self.building = HostGroup(id=uuid.uuid4(), name="SU5", parent_id=None)
        self.floor = HostGroup(id=uuid.uuid4(), name="1 этаж", parent_id=self.building.id)
        self.room = HostGroup(id=uuid.uuid4(), name="SU5-K104", parent_id=self.floor.id)
        self.groups = {g.id: g for g in (self.building, self.floor, self.room)}
        self.host = Host(id=uuid.uuid4(), hostname="SU5-K104-W09", group_id=self.room.id)

    def assign(self, kind, wp, host=None, group=None):
        return WallpaperAssignment(id=uuid.uuid4(), host_id=host, group_id=group, kind=kind, wallpaper_id=wp.id, wallpaper=wp)

    def test_nothing_assigned_means_unmanaged(self):
        self.assertEqual(effective_wallpapers(self.host, [], self.groups), {DESKTOP: None, LOCK_SCREEN: None})

    def test_nearest_group_wins_and_kinds_are_independent(self):
        autumn, winter, lock = wallpaper("autumn"), wallpaper("winter"), wallpaper("lock")
        result = effective_wallpapers(self.host, [
            self.assign(DESKTOP, autumn, group=self.building.id),
            self.assign(DESKTOP, winter, group=self.floor.id),
            self.assign(LOCK_SCREEN, lock, group=self.building.id),
        ], self.groups)
        self.assertIs(result[DESKTOP], winter)
        self.assertIs(result[LOCK_SCREEN], lock)

    def test_own_assignment_beats_the_group(self):
        group_wp, own = wallpaper("group"), wallpaper("own")
        result = effective_wallpapers(self.host, [
            self.assign(DESKTOP, group_wp, group=self.room.id),
            self.assign(DESKTOP, own, host=self.host.id),
        ], self.groups)
        self.assertIs(result[DESKTOP], own)

    def test_other_hosts_and_groups_do_not_apply(self):
        other_group = HostGroup(id=uuid.uuid4(), name="SU7", parent_id=None)
        result = effective_wallpapers(self.host, [
            self.assign(DESKTOP, wallpaper("x"), host=uuid.uuid4()),
            self.assign(DESKTOP, wallpaper("y"), group=other_group.id),
        ], {**self.groups, other_group.id: other_group})
        self.assertIsNone(result[DESKTOP])

    def test_target_for_the_agent(self):
        wp = wallpaper("autumn")
        self.assertEqual(wallpaper_target(wp), {"id": str(wp.id), "sha256": wp.sha256, "file_name": "autumn.jpg", "style": "4"})
        self.assertIsNone(wallpaper_target(None))


class SchemaTests(unittest.TestCase):
    def test_heartbeat_carries_the_wallpaper_report(self):
        payload = AgentHeartbeatRequest(machine_id=str(uuid.uuid4()), os="windows_11", wallpaper={
            "desktop": {"path": "C:\\wallpaper_new.png", "sha256": SHA, "source": "policy"},
            "lock_screen": None, "applied_desktop_id": None, "applied_lock_screen_id": None, "error": None,
            "thumbnails": [{"sha256": SHA, "jpeg_base64": "/9j/4AAQ"}],
        })
        self.assertEqual(payload.wallpaper.desktop.source, "policy")
        self.assertEqual(payload.wallpaper.thumbnails[0].sha256, SHA)

    def test_bad_hashes_are_rejected(self):
        with self.assertRaises(ValidationError):
            AgentHeartbeatRequest(machine_id=str(uuid.uuid4()), os="windows_11", wallpaper={"desktop": {"path": "C:\\a.png", "sha256": "../../x"}})

    def test_assign_request(self):
        wid = str(uuid.uuid4())
        request = WallpaperAssignRequest(host_ids=[uuid.uuid4()], desktop=wid.upper(), lock_screen="clear", apply_at="2026-10-20T08:00:00")
        self.assertEqual(request.desktop, wid)
        self.assertEqual(request.lock_screen, "clear")
        # Время без пояса — екатеринбургское
        self.assertEqual(request.apply_at.astimezone(timezone.utc), datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc))
        with self.assertRaises(ValidationError):
            WallpaperAssignRequest(host_ids=[uuid.uuid4()], desktop="autumn.jpg")


if __name__ == "__main__":
    unittest.main()
