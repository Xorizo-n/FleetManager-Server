"""Strict release contract shared by the host updater and release builder."""
import hashlib
import io
import json
import re
import tarfile
import urllib.request
from pathlib import Path

REPO = "Xorizo-n/FleetManager-Server"
TAG = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")
MAX_BUNDLE = 32 * 1024 * 1024


def version(tag):
    match = TAG.fullmatch(tag or "")
    if not match:
        raise ValueError("Ожидалась стабильная версия vX.Y.Z")
    return tuple(map(int, match.groups()))


def get(url, limit=1024 * 1024):
    request = urllib.request.Request(url, headers={"User-Agent": "FleetManager-Updater", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Превышен размер файла релиза")
    return data


def manifest(data, tag):
    version(tag)
    if data.get("format") != 1 or data.get("version") != tag:
        raise ValueError("Неподдерживаемый комплект обновления")
    if not re.fullmatch(r"[0-9a-f]{40}", data.get("commit", "")):
        raise ValueError("Не указан коммит релиза")
    if not re.fullmatch(r"[0-9a-f]{64}", data.get("bundle_sha256", "")):
        raise ValueError("Не указана контрольная сумма комплекта")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", data.get("schema_revision", "")):
        raise ValueError("Не указана версия схемы БД")
    for component in ("backend", "frontend"):
        expected = rf"ghcr\.io/xorizo-n/fleet-manager-{component}@sha256:[0-9a-f]{{64}}"
        if not re.fullmatch(expected, data.get("images", {}).get(component, "")):
            raise ValueError("Образ не принадлежит FleetManager или не закреплён по digest")
    return data


def release(tag=None):
    if tag is not None:
        version(tag)
    suffix = f"tags/{tag}" if tag else "latest"
    row = json.loads(get(f"https://api.github.com/repos/{REPO}/releases/{suffix}"))
    tag = row.get("tag_name")
    version(tag)
    if row.get("draft") or row.get("prerelease"):
        raise ValueError("Доступны только опубликованные стабильные релизы")
    # Use only canonical asset URLs, never arbitrary URLs supplied in a manifest.
    base = f"https://github.com/{REPO}/releases/download/{tag}/"
    names = {a["name"] for a in row.get("assets", [])}
    if not {"platform.json", "platform.tar.gz"} <= names:
        raise ValueError("В релизе нет готового комплекта платформы")
    data = manifest(json.loads(get(base + "platform.json")), tag)
    return {**data, "notes": (row.get("body") or "")[:20000],
            "published_at": row.get("published_at"), "url": f"https://github.com/{REPO}/releases/tag/{tag}"}


def unpack(data, destination, expected_hash):
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise ValueError("Контрольная сумма комплекта не совпадает")
    destination = Path(destination)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = archive.getmembers()
        if sum(m.size for m in members) > MAX_BUNDLE or len(members) > 1000:
            raise ValueError("Превышен размер распакованного комплекта")
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or "\\" in member.name or not (member.isfile() or member.isdir()):
                raise ValueError("Недопустимый путь в комплекте")
            if path.parts[0] not in {"compose.json", "ansible"}:
                raise ValueError("Неизвестный файл в комплекте")
        for member in members:
            target = destination / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
    if not (destination / "compose.json").is_file():
        raise ValueError("В комплекте нет compose.json")
