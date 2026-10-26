"""Понятное название, описание и файлы шары плейбука — из самого плейбука.

Название — name первого play, описание и файлы — переменные fm_description и fm_files в его vars
(Ansible их не использует). fm_files — маски от корня шары (settings.soft_share_dir): «npp.*.msi»,
«netfx3/*.cab»; папка — с «/» в конце. Каталог показывает, есть ли каждый файл в шаре, чтобы
запуск без установщика было видно до запуска, а не по ошибке на всех ПК.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath

from config import settings


@dataclass(frozen=True)
class PlaybookMeta:
    title: str | None = None
    description: str | None = None
    files: tuple[str, ...] = ()


def read_meta(path: Path) -> PlaybookMeta:
    """Метаданные плейбука; разбор кэшируется по времени изменения файла."""
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return PlaybookMeta()
    return _parse(str(path), mtime)


@lru_cache(maxsize=2048)
def _parse(path: str, _mtime: int) -> PlaybookMeta:
    try:
        import yaml

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:  # noqa: BLE001 — битый YAML: каталог показывает имя файла
        return PlaybookMeta()
    if not (isinstance(data, list) and data and isinstance(data[0], dict)):
        return PlaybookMeta()
    play = data[0]
    variables = play.get("vars") if isinstance(play.get("vars"), dict) else {}
    description = variables.get("fm_description")
    files = variables.get("fm_files") or []
    return PlaybookMeta(
        title=str(play["name"]).strip() if play.get("name") else None,
        description=" ".join(str(description).split()) if description else None,
        files=tuple(str(f).strip() for f in files if isinstance(f, (str, int, float)) and str(f).strip()) if isinstance(files, list) else (),
    )


def playbook_meta(repo_path: str | None, playbook_name: str | None) -> PlaybookMeta:
    if not repo_path or not playbook_name:
        return PlaybookMeta()
    base = Path(repo_path).resolve()
    target = (base / playbook_name).resolve()
    if base not in target.parents:  # путь задачи — только внутри репозитория
        return PlaybookMeta()
    return read_meta(target)


def share_files(patterns: tuple[str, ...] | list[str]) -> list[dict]:
    """Каждая маска fm_files: есть ли в шаре и какой файл возьмёт плейбук (самый новый по имени)."""
    root = Path(settings.soft_share_dir)
    result = []
    for pattern in patterns:
        relative = PurePosixPath(pattern.rstrip("/"))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            result.append({"pattern": pattern, "present": False, "found": None})
            continue
        if pattern.endswith("/"):
            present = (root / relative).is_dir()
            found = str(relative) if present else None
        else:
            try:
                matches = sorted(p.relative_to(root).as_posix() for p in root.glob(str(relative)) if p.is_file())
            except (OSError, ValueError):
                matches = []
            present = bool(matches)
            found = matches[-1] if matches else None
        result.append({"pattern": pattern, "present": present, "found": found})
    return result
