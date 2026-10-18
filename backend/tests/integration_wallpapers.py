"""Сквозная проверка обоев на настоящей PostgreSQL (не входит в unittest discover).

DATABASE_URL должен указывать на пустую копию схемы, а WALLPAPER_DIR — на временный каталог:
    python tests/integration_wallpapers.py
"""

import io
import uuid
from datetime import datetime, timedelta, timezone

from PIL import Image

from database import SessionLocal
from models.host import Host, HostGroup
from models.wallpaper import WallpaperAssignment, WallpaperSchedule
from schemas.agent import AgentWallpaperReport
from services.wallpapers import CLEAR, WallpaperError, apply_assignment, apply_due_schedules, heartbeat_wallpaper, store_report, store_upload


def png(color) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1920, 1080), color).save(out, "PNG")
    return out.getvalue()


db = SessionLocal()
building = HostGroup(name=f"T{uuid.uuid4().hex[:6]}")
db.add(building)
db.flush()
room = HostGroup(name=f"{building.name}-101", parent_id=building.id)
db.add(room)
db.flush()
host = Host(hostname=f"{room.name}-W01", ip_address="10.99.0.1", os="windows_11", status="online", group_id=room.id)
db.add(host)
db.flush()

autumn = store_upload(db, png((200, 120, 40)), "Осень", "autumn.png", None)
winter = store_upload(db, png((220, 230, 255)), None, "winter.png", None)
db.flush()
try:
    store_upload(db, png((200, 120, 40)), "Дубль", "dup.png", None)
    raise AssertionError("duplicate upload accepted")
except WallpaperError as exc:
    print("duplicate refused:", exc)

assert heartbeat_wallpaper(db, host) == {"desktop": None, "lock_screen": None, "thumbnails": []}

# Корпус: рабочий стол и экран блокировки; аудитория: свой рабочий стол
assert apply_assignment(db, [], [building.id], str(autumn.id), str(autumn.id), None) == 2
assert apply_assignment(db, [], [room.id], str(winter.id), None, None) == 1
db.flush()
wp = heartbeat_wallpaper(db, host)
assert wp["desktop"]["id"] == str(winter.id) and wp["lock_screen"]["id"] == str(autumn.id), wp
assert wp["desktop"]["sha256"] == winter.sha256 and wp["desktop"]["file_name"].endswith(".png")

# Повтор того же назначения ничего не меняет; снятие у аудитории возвращает обои корпуса
assert apply_assignment(db, [], [room.id], str(winter.id), None, None) == 0
assert apply_assignment(db, [], [room.id], CLEAR, None, None) == 1
db.flush()
assert heartbeat_wallpaper(db, host)["desktop"]["id"] == str(autumn.id)

# Отчёт агента: обои образа не из каталога — сервер просит миниатюру, после неё больше не просит
foreign = "b" * 64
report = AgentWallpaperReport(desktop={"path": "C:\\wallpaper_new.png", "sha256": foreign, "source": "policy"},
                              lock_screen={"path": "C:\\x.png", "sha256": autumn.sha256, "source": "policy"})
store_report(db, host, report, datetime.now(timezone.utc))
db.flush()
assert heartbeat_wallpaper(db, host)["thumbnails"] == [foreign]
thumb = io.BytesIO()
Image.new("RGB", (320, 180), (1, 2, 3)).save(thumb, "JPEG")
import base64

report.thumbnails = [{"sha256": foreign, "jpeg_base64": base64.b64encode(thumb.getvalue()).decode()}]
report = AgentWallpaperReport.model_validate(report.model_dump())
store_report(db, host, report, datetime.now(timezone.utc))
db.flush()
assert heartbeat_wallpaper(db, host)["thumbnails"] == []
assert host.wallpaper_state["desktop"]["sha256"] == foreign and "thumbnails" not in host.wallpaper_state

# Смена по расписанию: в прошлом — применяется, в будущем — ждёт
now = datetime.now(timezone.utc)
due = WallpaperSchedule(apply_at=now - timedelta(minutes=1), host_ids=[str(host.id)], group_ids=[], desktop=str(winter.id), lock_screen=CLEAR)
later = WallpaperSchedule(apply_at=now + timedelta(days=1), host_ids=[], group_ids=[str(building.id)], desktop=CLEAR, lock_screen=None)
db.add_all([due, later])
db.commit()
assert apply_due_schedules(db, now) == 1
db.refresh(due)
db.refresh(later)
assert (due.status, later.status) == ("applied", "pending"), (due.status, due.result, later.status)
wp = heartbeat_wallpaper(db, host)
# У ПК своё назначение рабочего стола; экран блокировки «снят» у ПК — остаётся от корпуса
assert wp["desktop"]["id"] == str(winter.id) and wp["lock_screen"]["id"] == str(autumn.id), wp

# Назначение группы заменяет свои назначения аудиторий и ПК внутри: «обои на весь корпус»
# Аудитория: собственное назначение ПК (из расписания выше) снимается, аудитории ставится своё
assert apply_assignment(db, [], [room.id], str(autumn.id), None, None) == 2
db.flush()
assert heartbeat_wallpaper(db, host)["desktop"]["id"] == str(autumn.id)
# Корпус: назначение аудитории снимается, у корпуса меняется
assert apply_assignment(db, [], [building.id], str(winter.id), None, None) == 2
db.flush()
assert db.query(WallpaperAssignment).filter(WallpaperAssignment.kind == "desktop", WallpaperAssignment.group_id == room.id).count() == 0
assert heartbeat_wallpaper(db, host)["desktop"]["id"] == str(winter.id)
# ПК, выбранный в том же запросе отдельно, получает своё
assert apply_assignment(db, [host.id], [building.id], str(autumn.id), None, None) == 2
db.flush()
assert heartbeat_wallpaper(db, host)["desktop"]["id"] == str(autumn.id)
# Снятие у корпуса тоже действует на всю группу
assert apply_assignment(db, [], [building.id], CLEAR, None, None) == 2
db.flush()
assert heartbeat_wallpaper(db, host)["desktop"] is None
assert heartbeat_wallpaper(db, host)["lock_screen"]["id"] == str(autumn.id)
db.commit()

# Удаление группы снимает её назначения
extra = HostGroup(name=f"{building.name}-X")
db.add(extra)
db.flush()
apply_assignment(db, [], [extra.id], str(autumn.id), None, None)
db.commit()
db.delete(extra)
db.commit()
assert db.query(WallpaperAssignment).filter(WallpaperAssignment.group_id == extra.id).count() == 0
print("integration OK")
