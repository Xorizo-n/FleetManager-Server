"""Точка раздачи: зеркало /mnt/soft-share на сервере ближе к ПК (сейчас 10.152.240.10:8088).

Зачем. Плейбуки копировали установщики win_copy по SSH — около 30 Мбит/с на ПК, и все
файлы шли через бэкенд с его 1 Гбит/с. С точки раздачи ПК скачивает файл сам по HTTP
(сотни Мбит/с на ПК, 10 Гбит/с у сервера), а бэкенд лишь подписывает ссылку.

Как устроено:
* sync_distribution — rsync по SSH (ключ в /mnt/dist-ssh, на точке раздачи rrsync пускает
  только в её папку) после загрузки файла, после обновления установщика агента и раз в
  15 минут. Источник правды — бэкенд: удалённое здесь удаляется и там.
* Манифест (DIST_MANIFEST_PATH): путь от корня шары → размер, mtime и SHA-256 файла, каким
  он ушёл на точку раздачи. Файл, изменённый после синхронизации, в манифесте не совпадёт
  по размеру или mtime — такой ПК получит прежним способом.
* Ссылки — nginx secure_link: md5(срок + путь + секрет), без подписи 403. Секрет общий с
  /etc/nginx/fleet-dist-secret.conf на точке раздачи.
* Плейбуки качают через action-плагин fm_fetch (ansible_plugins/action/fm_fetch.py), агент —
  по ссылке из предложения обновления; при любой ошибке — прежний путь через бэкенд.
"""
from __future__ import annotations

import base64
import contextlib
import fcntl
import hashlib
import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

from celery_app import celery_app
from config import settings

logger = logging.getLogger(__name__)

# Не раздаются: временные файлы загрузки через UI и служебные папки
EXCLUDED_DIRS = (".upload-tmp", "lost+found")
EXCLUDED_SUFFIXES = (".part",)
SYNC_TIMEOUT = 12 * 3600
HEALTH_TIMEOUT = 5


def enabled() -> bool:
    return bool(settings.dist_url and settings.dist_secret)


def route_pins() -> list[dict]:
    """Адреса, до которых агент закрепляет маршрут мимо VPN (в ответе на heartbeat, поле pin_routes).

    Полнотуннельный VPN на ПК забирает и трафик к точке раздачи: nginx видит адрес из VPN-пула и
    отвечает 403, поэтому установщик агента и файлы плейбуков шли через бэкенд (~30 Мбит/с).
    Агент делает до точки раздачи такой же /32 через шлюз физической карты, как до сервера."""
    if not enabled():
        return []
    parsed = urlsplit(settings.dist_url)
    if not parsed.hostname:
        return []
    return [{"host": parsed.hostname, "port": parsed.port or (443 if parsed.scheme == "https" else 80)}]


def _excluded(rel: str) -> bool:
    parts = rel.split("/")
    return (parts[0] in EXCLUDED_DIRS or any(p.startswith(".") for p in parts)
            or rel.endswith(EXCLUDED_SUFFIXES))


def sign_path(rel: str, ttl_seconds: int | None = None, now: float | None = None) -> str:
    """Подписанная ссылка на файл точки раздачи; rel — путь от корня шары."""
    expires = int((now or time.time()) + (ttl_seconds or settings.dist_link_ttl_seconds))
    uri = "/" + rel.lstrip("/")
    digest = hashlib.md5(f"{expires}{uri} {settings.dist_secret}".encode()).digest()
    md5 = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return f"{settings.dist_url.rstrip('/')}{quote(uri)}?md5={md5}&expires={expires}"


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def load_manifest() -> dict:
    return _read_json(settings.dist_manifest_path).get("files") or {}


def link_for(path: str, ttl_seconds: int | None = None) -> tuple[str, str] | None:
    """(ссылка, sha256) для файла шары, если на точке раздачи лежит именно он; иначе None."""
    if not enabled():
        return None
    root = os.path.realpath(settings.soft_share_dir)
    real = os.path.realpath(path)
    if not real.startswith(root + os.sep):
        return None
    rel = os.path.relpath(real, root).replace(os.sep, "/")
    entry = load_manifest().get(rel)
    if not entry:
        return None
    try:
        stat = os.stat(real)
    except OSError:
        return None
    if [stat.st_size, stat.st_mtime_ns] != entry[:2]:
        return None
    return sign_path(rel, ttl_seconds), entry[2]


# --- синхронизация ---

def _snapshot(root: str) -> dict[str, tuple[int, int]]:
    files = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/") + "/"
        dirnames[:] = [d for d in dirnames if not _excluded(rel_dir + d)]
        for name in filenames:
            rel = rel_dir + name
            if _excluded(rel):
                continue
            path = os.path.join(dirpath, name)
            with contextlib.suppress(OSError):
                if os.path.isfile(path) and not os.path.islink(path):
                    stat = os.stat(path)
                    files[rel] = (stat.st_size, stat.st_mtime_ns)
    return files


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rsync_command(source: str) -> list[str]:
    ssh_dir = settings.dist_ssh_dir
    ssh = (f"ssh -i {ssh_dir}/id_ed25519 -o UserKnownHostsFile={ssh_dir}/known_hosts"
           " -o StrictHostKeyChecking=yes -o BatchMode=yes -o ConnectTimeout=15")
    excludes = [f"--exclude=/{d}/" for d in EXCLUDED_DIRS] + [f"--exclude=*{s}" for s in EXCLUDED_SUFFIXES]
    return ["rsync", "-rt", "--delete", "--delete-delay", "--chmod=D755,F644", "--partial",
            "--partial-dir=.rsync-partial", "--exclude=.*", *excludes,
            f"--bwlimit={settings.dist_bwlimit_kbps}", "--timeout=600", "--stats", "-e", ssh,
            source.rstrip("/") + "/", f"{settings.dist_rsync_target}:"]


def check_health() -> bool:
    try:
        with urllib.request.urlopen(settings.dist_url.rstrip("/") + "/health", timeout=HEALTH_TIMEOUT) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sync_once() -> dict:
    root = settings.soft_share_dir
    before = _snapshot(root)
    started = time.monotonic()
    proc = subprocess.run(rsync_command(root), capture_output=True, text=True, timeout=SYNC_TIMEOUT)
    if proc.returncode not in (0, 24):  # 24 — файл исчез во время передачи: не ошибка
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        raise RuntimeError(f"rsync завершился с кодом {proc.returncode}: {' '.join(tail)}")
    after = _snapshot(root)

    old = load_manifest()
    files = {}
    for rel, stat in after.items():
        if before.get(rel) != stat:
            continue  # менялся во время передачи — дождётся следующей синхронизации
        cached = old.get(rel)
        if cached and cached[:2] == list(stat):
            files[rel] = cached
            continue
        with contextlib.suppress(OSError):
            files[rel] = [stat[0], stat[1], _sha256(os.path.join(root, rel))]
    _write_json(settings.dist_manifest_path, {"synced_at": _now(), "files": files})
    return {"files": len(files), "bytes": sum(v[0] for v in files.values()),
            "pending": len(after) - len(files), "seconds": round(time.monotonic() - started, 1)}


def _lock_path() -> str:
    return settings.dist_manifest_path + ".lock"


def _again_path() -> str:
    return settings.dist_manifest_path + ".again"


def sync() -> dict:
    """Одна синхронизация за раз; запрос во время идущей повторяет её сразу после."""
    if not enabled() or not settings.dist_rsync_target:
        return {"skipped": "точка раздачи не настроена"}
    with open(_lock_path(), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            open(_again_path(), "w").close()
            return {"skipped": "синхронизация уже идёт, повторится после неё"}
        state = _read_json(settings.dist_state_path)
        result: dict = {}
        for _ in range(3):
            with contextlib.suppress(FileNotFoundError):
                os.unlink(_again_path())
            state.update(last_attempt=_now(), running=True)
            _write_json(settings.dist_state_path, state)
            try:
                result = _sync_once()
                state.update(last_success=_now(), error=None, **result)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Distribution sync failed")
                state["error"] = str(exc)[:500]
                result = {"error": state["error"]}
            if not os.path.exists(_again_path()):
                break
        state.update(running=False, healthy=check_health(), checked_at=_now())
        _write_json(settings.dist_state_path, state)
        return result


@celery_app.task(name="services.distribution.sync_distribution", ignore_result=True)
def sync_distribution():
    return sync()


def request_sync() -> None:
    """Синхронизировать в фоне (после загрузки файла); без Celery — молча пропустить."""
    if enabled():
        with contextlib.suppress(Exception):
            sync_distribution.delay()


def _sync_running() -> bool:
    """Держит ли кто-то блокировку: флаг running в файле остался бы и после убитого воркера."""
    try:
        with open(_lock_path(), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock, fcntl.LOCK_UN)
            return False
    except BlockingIOError:
        return True
    except OSError:
        return False


def status() -> dict:
    state = _read_json(settings.dist_state_path)
    return {
        "enabled": enabled(),
        "url": settings.dist_url or None,
        "running": _sync_running(),
        "healthy": state.get("healthy"),
        "checked_at": state.get("checked_at"),
        "last_attempt": state.get("last_attempt"),
        "last_success": state.get("last_success"),
        "error": state.get("error"),
        "files": state.get("files"),
        "bytes": state.get("bytes"),
        "pending": state.get("pending"),
    }
