import json
import os
import urllib.error
import urllib.request

from celery_app import celery_app
from config import settings

GITHUB_REPO = "Xorizo-n/FleetManager-Agent"
INSTALLER_FILENAME = "FleetManagerAgent-Setup.exe"
VERSION_SIDECAR = INSTALLER_FILENAME + ".version"
USER_AGENT = "FleetManager-Server-agent-installer-sync"
REQUEST_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 120


def _latest_release() -> dict:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return json.load(resp)


def _installed_version(soft_dir: str) -> str | None:
    path = os.path.join(soft_dir, VERSION_SIDECAR)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def _download_asset(url: str, dest: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest + ".part"
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp, open(tmp, "wb") as out:
        while chunk := resp.read(1024 * 1024):
            out.write(chunk)
    os.replace(tmp, dest)


def sync_agent_installer() -> dict:
    """Pull the latest FleetManager-Agent installer release into soft_share_dir if it's newer."""
    soft_dir = settings.soft_share_dir
    if not os.path.isdir(soft_dir):
        return {"updated": False, "reason": f"Папка установочников недоступна: {soft_dir}"}

    try:
        release = _latest_release()
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"updated": False, "reason": f"GitHub недоступен: {exc}"}

    tag = release.get("tag_name")
    asset = next(
        (a for a in release.get("assets", []) if a.get("name") == INSTALLER_FILENAME),
        None,
    )
    if not tag or asset is None:
        return {"updated": False, "reason": "В последнем релизе нет FleetManagerAgent-Setup.exe"}

    if _installed_version(soft_dir) == tag:
        return {"updated": False, "reason": "Уже актуальная версия", "version": tag}

    dest = os.path.join(soft_dir, INSTALLER_FILENAME)
    _download_asset(asset["browser_download_url"], dest)

    with open(os.path.join(soft_dir, VERSION_SIDECAR), "w", encoding="utf-8") as f:
        f.write(tag)

    return {"updated": True, "version": tag}


@celery_app.task(name="services.agent_installer_sync.sync_agent_installer_task")
def sync_agent_installer_task():
    sync_agent_installer()
