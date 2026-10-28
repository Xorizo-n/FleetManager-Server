"""От чьего имени плейбук выполняется на ПК: инициатор задачи или учётка установки агента.

Сервер входит на ПК по SSH ключом Fleet Manager, который агент кладёт в
administrators_authorized_keys. OpenSSH на Windows принимает этот файл для любого члена
локальной группы «Администраторы» (Match Group administrators), поэтому тем же ключом
можно войти и под доменной учёткой инициатора — без пароля, если она в администраторах
ПК (на SU5/SU7 туда входит AT\\IRITRTF OOD Staff). Так в журнале безопасности Windows
виден реальный человек.

Перед запуском каждый ПК пробуется входом под инициатором (`whoami`). Где вход не
прошёл — учётка не администратор ПК, отключена в домене, ПК недоступен, — остаётся
учётка, под которой ставили агент (запасная). Инициатор — доменный пользователь Fleet
Manager: кто запустил вручную, для расписания — его владелец (кто создал или последним
изменил). Фоновые задачи (сканирования, обновление и проверка агента) этим модулем не
пользуются и всегда идут от учётки установки.

Если вход отклонён и под учёткой установки тоже (домен на ПК недоступен, учётка отключена),
пробуется локальный администратор тем же ключом (services/local_admin.py): где он
прошёл, плейбук идёт под ним, а не падает с «Connection reset».
"""
from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from config import settings
from models.credential import CredentialType
from models.host import Host
from models.user import User
from services import local_admin
from services.host_target import resolve_host_target
from services.inventory_generator import host_group_credential

PROBE_TIMEOUT = 75  # первый вход создаёт профиль пользователя на ПК: до 30 с и больше
CONNECT_TIMEOUT = 10


@dataclass
class RunAsPlan:
    """login — под кем пробовали (None — инициатора нет или он не подходит, reason — почему)."""

    login: str | None = None
    reason: str | None = None
    as_user: set[str] = field(default_factory=set)
    fallback: dict[str, str] = field(default_factory=dict)
    # {host_id: почему доменный вход не прошёл} — эти ПК идут под локальным администратором
    local: dict[str, str] = field(default_factory=dict)

    def overrides(self) -> dict[str, str]:
        result = {host_id: self.login for host_id in self.as_user} if self.login else {}
        local = local_admin.login()
        if local:
            result.update({host_id: local for host_id in self.local})
        return result

    def summary(self) -> dict:
        return {"login": self.login, "reason": self.reason, "as_user": sorted(self.as_user), "fallback": self.fallback,
                "local": self.local}


def initiator_login(db, user_id) -> tuple[str | None, str | None]:
    """(логин для SSH, причина отказа). Только активные доменные пользователи."""
    from services import ldap_config

    if not settings.playbook_run_as_initiator:
        return None, "запуск от имени инициатора выключен (PLAYBOOK_RUN_AS_INITIATOR)"
    if user_id is None:
        return None, "у задачи нет инициатора"
    user = db.get(User, user_id)
    if user is None:
        return None, "инициатор удалён из Fleet Manager"
    if user.auth_source != "ldap":
        return None, f"{user.username} — локальная учётная запись Fleet Manager, не доменная"
    if not user.is_active:
        return None, f"{user.username} заблокирован в Fleet Manager"
    if not ldap_config.current().enabled:
        return None, "вход через домен выключен"
    return f"{settings.ldap_netbios_domain}\\{user.username}", None


def _ssh_key(host: Host) -> str | None:
    from services.ansible_runner import credential_vars

    credential = host.credential or host_group_credential(host)
    if credential is None or credential.type != CredentialType.ssh_key:
        return None
    return credential_vars(credential).get("ansible_ssh_private_key_file")


# Соединение было, но вход отклонён: учётка или домен, а не сеть — есть смысл пробовать другую учётку
_REJECTED = ("permission denied", "connection reset", "connection closed by")


def _rejected(error: str | None, stderr: str = "") -> bool:
    return bool(error) and any(s in stderr.lower() for s in _REJECTED)


def _classify(stderr: str) -> str:
    text = stderr.lower()
    if "permission denied" in text:
        return "вход не принят: учётка не в локальных администраторах ПК или отключена в домене"
    if "identification has changed" in text or "host key verification failed" in text:
        return "изменился SSH-ключ ПК"
    if any(s in text for s in ("timed out", "no route", "connection refused", "could not resolve", "network is unreachable")):
        return "ПК недоступен по SSH"
    line = next((ln.strip() for ln in stderr.splitlines() if ln.strip()), "")
    return f"вход не удался: {line[:160]}" if line else "вход не удался"


def probe_host(host: Host, login: str) -> str | None:
    """None — вход под login прошёл и whoami вернул его же, иначе причина."""
    return _probe(host, login)[0]


def _probe(host: Host, login: str) -> tuple[str | None, bool]:
    """(причина или None, отклонён ли именно вход — а не сеть или ключ ПК)."""
    key = _ssh_key(host)
    if not key:
        return "у ПК нет SSH-ключа Fleet Manager", False
    target = resolve_host_target(host.hostname, host.ip_address)
    port = str(host.ssh_port or settings.ansible_ssh_port)
    command = [
        "ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={CONNECT_TIMEOUT}", "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ControlMaster=no", "-o", "PasswordAuthentication=no", "-o", "KbdInteractiveAuthentication=no",
        "-o", "IdentitiesOnly=yes", "-i", key, "-p", port, "-l", login, target, "whoami",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=PROBE_TIMEOUT, env={**os.environ, "LC_ALL": "C"})
    except subprocess.TimeoutExpired:
        return "ПК не ответил на вход вовремя", False
    if result.returncode != 0:
        error = _classify(result.stderr)
        return error, _rejected(error, result.stderr)
    who = (result.stdout or "").strip().splitlines()
    got = who[-1].strip().lower() if who else ""
    # Локальная учётка отвечает whoami как «имя-пкdmin»
    if not who or (got != login.lower() and got.rsplit("\\", 1)[-1] != login.lower()):
        return f"вход прошёл под другой учёткой ({who[-1].strip() if who else '—'})", False
    return None, False


def plan(db, host_ids: list[str], user_id) -> RunAsPlan:
    login, reason = initiator_login(db, user_id)
    if login is None:
        return RunAsPlan(reason=reason)
    hosts = [h for h in db.query(Host).filter(Host.id.in_(host_ids)).all()]
    result = RunAsPlan(login=login)
    with ThreadPoolExecutor(max_workers=max(1, settings.run_as_probe_parallelism)) as pool:
        for host, (kind, error) in zip(hosts, pool.map(lambda h: _decide(h, login), hosts)):
            if kind == "as_user":
                result.as_user.add(str(host.id))
            elif kind == "local":
                result.local[str(host.id)] = error
            else:
                result.fallback[str(host.id)] = error
    return result


def _install_login(host: Host) -> str | None:
    credential = host.credential or host_group_credential(host)
    return credential.login if credential is not None else None


def _decide(host: Host, login: str) -> tuple[str, str | None]:
    """(as_user | fallback | local, причина). Вход отклонён под инициатором и под доменной учёткой
    установки — пробуем локального администратора: значит, на ПК не работает сам домен."""
    error, rejected = _probe(host, login)
    if error is None:
        return "as_user", None
    local = local_admin.login()
    if not rejected or not local or not local_admin.usable(getattr(host, "ssh_state", None)):
        return "fallback", error
    install = _install_login(host)
    if local_admin.is_domain_login(install) and install.lower() != login.lower():
        install_error, install_rejected = _probe(host, install)
        if install_error is None or not install_rejected:
            return "fallback", error
    elif not local_admin.is_domain_login(install):
        return "fallback", error  # установка и так под локальной учёткой
    if _probe(host, local)[0] is None:
        return "local", error
    return "fallback", error


def log_lines(result: RunAsPlan, names: dict[str, str]) -> list[str]:
    """Строки в начало лога задачи: от кого выполнялось и почему где-то — нет."""
    if result.login is None:
        return [f"[Fleet Manager] Выполняется от учётки установки агента: {result.reason}."]
    lines = []
    if result.as_user:
        lines.append(f"[Fleet Manager] Выполняется от имени {result.login} на {len(result.as_user)} ПК.")
    if result.local:
        lines.append(f"[Fleet Manager] Под локальным администратором {local_admin.login()} на {len(result.local)} ПК — доменный вход не прошёл:")
        lines.extend(f"    {names.get(host_id, host_id)}: {why}" for host_id, why in sorted(result.local.items(), key=lambda x: names.get(x[0], x[0])))
    if result.fallback:
        lines.append(f"[Fleet Manager] От учётки установки агента на {len(result.fallback)} ПК — вход под {result.login} не прошёл:")
        lines.extend(f"    {names.get(host_id, host_id)}: {why}" for host_id, why in sorted(result.fallback.items(), key=lambda x: names.get(x[0], x[0])))
    return lines
