"""Локальные плейбуки — созданные в редакторе Fleet Manager и хранящиеся только на этом сервере.

Это отдельный источник «Fleet Manager» (PlaybookRepo с kind="local") рядом с git-репозиториями:
запуск, расписания и журнал задач работают с ним так же. Каталог лежит в томе ansible_data,
который видят и backend, и воркер Celery. Плейбуки git-репозиториев здесь не правятся: правка
рабочей копии сломала бы следующий git pull — их копируют в локальные.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from models.playbook import PlaybookRepo

LOCAL = "local"
LOCAL_REPO_NAME = "Fleet Manager"
MAX_BYTES = 256 * 1024
SYNTAX_CHECK_TIMEOUT = 60
# Имя файла и не больше одной папки: install/firefox.yml. Без «..», пробелов и скрытых файлов
PATH_RE = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9_-]{0,63}/)?[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\.ya?ml$")

TEMPLATE = """---
# name — понятное название в каталоге; fm_description — что делает плейбук (показывается при выборе
# и запуске); fm_files — маски файлов из шары, которые он берёт (каталог проверяет, что они есть).
- name: Новый плейбук
  hosts: Win_Hosts
  gather_facts: false
  ignore_unreachable: true
  vars:
    fm_description: >-
      Что делает плейбук — одним-двумя предложениями.
    fm_files: []
    ansible_remote_tmp: 'C:\\Windows\\Temp'
  tasks:
    - name: Проверить связь с ПК
      ansible.windows.win_ping:
"""


class PlaybookError(ValueError):
    """Текст ошибки показывается в редакторе."""


def local_dir() -> Path:
    return Path(settings.local_playbooks_dir)


def ensure_local_repo(db: Session) -> PlaybookRepo:
    repo = db.execute(select(PlaybookRepo).where(PlaybookRepo.kind == LOCAL)).scalar_one_or_none()
    local_dir().mkdir(parents=True, exist_ok=True)
    if repo is None:
        repo = PlaybookRepo(name=LOCAL_REPO_NAME, kind=LOCAL, git_url="", branch="", local_path=str(local_dir()))
        db.add(repo)
        db.commit()
        db.refresh(repo)
    return repo


def check_path(path: str) -> str:
    path = path.strip().replace("\\", "/")
    if not PATH_RE.match(path):
        raise PlaybookError("Имя файла: латиница, цифры, «_», «-», «.», окончание .yml; можно одну папку — install/firefox.yml")
    return path


def resolve(repo: PlaybookRepo, path: str) -> Path:
    """Файл внутри каталога репозитория; выход за его пределы — ошибка."""
    base = Path(repo.local_path).resolve()
    target = (base / path).resolve()
    if base not in target.parents or ".git" in target.relative_to(base).parts:
        raise PlaybookError("Файл вне каталога плейбуков")
    return target


def validate_structure(content: str) -> list:
    if not content.strip():
        raise PlaybookError("Плейбук пустой")
    if len(content.encode("utf-8")) > MAX_BYTES:
        raise PlaybookError(f"Плейбук больше {MAX_BYTES // 1024} КБ")
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (строка {mark.line + 1}, позиция {mark.column + 1})" if mark else ""
        raise PlaybookError(f"Ошибка YAML{where}: {getattr(exc, 'problem', None) or exc}") from exc
    if not isinstance(data, list) or not data:
        raise PlaybookError("Плейбук — это список play: начинается с «- name: …» и «hosts: …»")
    for index, play in enumerate(data, 1):
        if not isinstance(play, dict):
            raise PlaybookError(f"Play №{index} — не словарь")
        if "hosts" not in play and "import_playbook" not in play and "ansible.builtin.import_playbook" not in play:
            raise PlaybookError(f"У play №{index} не задано «hosts»")
    return data


def syntax_check(content: str) -> str | None:
    """ansible-playbook --syntax-check: модули, ключевые слова, шаблоны. None — всё в порядке, иначе вывод ошибки.

    Файл кладётся во временный каталог рядом с локальными плейбуками, чтобы относительные
    include и import разрешались так же, как при запуске."""
    local_dir().mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=local_dir(), prefix=".check-") as tmp:
        file = Path(tmp) / "playbook.yml"
        file.write_text(content, encoding="utf-8")
        env = {**os.environ, "ANSIBLE_NOCOLOR": "1", "ANSIBLE_FORCE_COLOR": "0", "ANSIBLE_DEPRECATION_WARNINGS": "0",
               "ANSIBLE_LOCALHOST_WARNING": "0", "ANSIBLE_INVENTORY_UNPARSED_WARNING": "0"}
        try:
            result = subprocess.run(["ansible-playbook", "--syntax-check", "-i", "localhost,", str(file)],
                                    capture_output=True, text=True, timeout=SYNTAX_CHECK_TIMEOUT, cwd=local_dir(), env=env)
        except FileNotFoundError:
            return None  # нет ansible (тесты вне контейнера) — остаётся проверка структуры
        except subprocess.TimeoutExpired:
            return "Проверка синтаксиса не уложилась в отведённое время"
    if result.returncode == 0:
        return None
    output = (result.stderr or result.stdout).replace(str(file), "playbook.yml").strip()
    lines = [line for line in output.splitlines() if not line.startswith("[WARNING]: Could not match supplied host pattern")]
    return "\n".join(lines)[-4000:] or "ansible-playbook --syntax-check завершился с ошибкой"


def check(content: str) -> str | None:
    """Полная проверка перед сохранением; None — можно сохранять."""
    try:
        validate_structure(content)
    except PlaybookError as exc:
        return str(exc)
    return syntax_check(content)


def write(target: Path, content: str) -> None:
    """Атомарная запись: воркер не прочитает наполовину записанный файл."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    tmp.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
    os.replace(tmp, target)


def prune_empty_dirs(repo: PlaybookRepo, start: Path) -> None:
    base = Path(repo.local_path).resolve()
    folder = start.parent
    while folder != base and base in folder.parents and not any(folder.iterdir()):
        folder.rmdir()
        folder = folder.parent
