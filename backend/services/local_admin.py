"""Запасной вход на ПК под локальным администратором, когда доменный вход не проходит.

Сервер входит на ПК ключом Fleet Manager из administrators_authorized_keys, а OpenSSH на
Windows принимает этот файл для любого члена локальной группы «Администраторы» (см.
services/run_as.py). Доменной учётке для входа нужен контроллер домена: при нарушенном
доверии (SU5-I203-W03) или недоступном контроллере (SU5-J108-W02 с VPN) sshd обрывает
соединение после обмена ключами, и ПК выпадает из Ansible, хотя агент шлёт heartbeat.
Отключённая или переименованная учётка (AT\\Alexey.Zadevalov на SU7-N205-OP, SU7-O108-OP,
SU7-Q205-OP) даёт то же самое.

Локальный администратор есть на каждом ПК: AutoDomain создаёт его при вводе в домен, пароль
аудитории ставит плейбук set_local_admin_password.yml из room-passwords. Пароль для входа не
нужен — тот же ключ. Вход под ним не зависит от домена.

Когда переходить на него:
* агент сообщил, что доверие с доменом нарушено или контроллер недоступен (domain_trust) —
  для всех задач, включая фоновые (build_full_inventory);
* перед запуском плейбука вход под доменной учёткой не прошёл, а под локальной прошёл
  (services/run_as.plan).
Агент сообщает, есть ли локальная учётка и в администраторах ли она (local_admin): если
нет — переходить некуда.
"""
from __future__ import annotations

from config import settings
from services.ssh_health import _fresh

DOMAIN_DOWN = ("broken", "unreachable")
# Что агент сообщает о локальной учётке: ok — есть, включена, в «Администраторах»
LOCAL_ADMIN_LABELS = {
    "missing": "нет",
    "disabled": "отключена",
    "not_admin": "не в «Администраторах»",
}


def login() -> str | None:
    return settings.local_admin_login if settings.local_admin_fallback and settings.local_admin_login else None


def is_domain_login(value: str | None) -> bool:
    return bool(value) and ("\\" in value or "@" in value)


def usable(state: dict | None) -> bool:
    """Можно ли пробовать локальную учётку: агент не сообщил, что её нет или она не годится."""
    return (state or {}).get("local_admin") not in LOCAL_ADMIN_LABELS


def domain_down(state: dict | None) -> str | None:
    """Почему доменный вход сейчас не сработает, по свежему отчёту агента; None — домен в порядке."""
    trust = (state or {}).get("domain_trust")
    if trust not in DOMAIN_DOWN or not _fresh(state, None):
        return None
    return "нарушено доверие с доменом" if trust == "broken" else "контроллер домена недоступен"


def preferred(host, current_login: str | None) -> str | None:
    """Локальный логин вместо доменного по отчёту агента; None — оставить как есть."""
    local = login()
    if not local or not is_domain_login(current_login):
        return None
    state = getattr(host, "ssh_state", None)
    if domain_down(state) and usable(state):
        return local
    return None
