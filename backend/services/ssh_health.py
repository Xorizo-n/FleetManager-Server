"""SSH на ПК по отчёту агента (heartbeat, поле ssh).

Агент с 2026.10.25 сам чинит, что может (запуск sshd, правило брандмауэра, PATH), и сообщает
остальное. Отсюда сервер берёт:
* список причин, по которым он не попадёт на ПК по SSH, — для карточки хоста;
* решение «heartbeat пришёл, но SSH заведомо закрыт» — тогда ожидающие задачи ПК не забирают:
  раньше они срывались с «Проверка не вернула результат» на каждом heartbeat;
* ключи хоста для known_hosts по id хоста, а не по IP (services/ansible_runner.py).
"""
from datetime import datetime, timedelta, timezone

# Отчёт старше этого не используется для решений: агент присылает его каждые 5 минут
FRESH_FOR = timedelta(minutes=20)

FIREWALL_RULE_LABELS = {
    "missing": "нет",
    "disabled": "выключено",
    "mismatch": "не совпадает с установщиком (порт, профиль или адрес сервера)",
}
# NetworkCategory из Get-NetConnectionProfile -> профиль брандмауэра
_PROFILE_OF_CATEGORY = {"DomainAuthenticated": "Domain", "Private": "Private", "Public": "Public"}


def store_ssh_report(host, report, now: datetime) -> None:
    """report — schemas.agent.AgentSshReport (схема импортирует models.host, отсюда без импорта)."""
    if report is None:
        return
    host.ssh_state = {**report.model_dump(mode="json"), "reported_at": now.isoformat()}


def _fresh(state: dict | None, now: datetime | None) -> bool:
    if not state:
        return False
    try:
        reported = datetime.fromisoformat(state.get("reported_at") or "")
    except ValueError:
        return False
    return (now or datetime.now(timezone.utc)) - reported <= FRESH_FOR


def _gpo_blocks(state: dict) -> list[str]:
    """Профили, где GPO игнорирует локальные правила и сама порт 22 не открывает, — из активных сейчас."""
    ignored = state.get("firewall_ignored_on") or []
    if not ignored or state.get("firewall_gpo_allows"):
        return []
    active = {_PROFILE_OF_CATEGORY.get(c, c) for c in state.get("network_profiles") or []}
    return [p for p in ignored if not active or p in active]


def _connection_problems(state: dict) -> list[str]:
    """Причины, по которым SSH-подключение с сервера не состоится."""
    problems = []
    if state.get("installed") is False:
        problems.append("OpenSSH Server не установлен")
    elif state.get("start_type") == "disabled":
        problems.append("служба sshd отключена (решение администратора или групповой политики)")
    elif state.get("listening") is False:
        problems.append("sshd не слушает порт 22")
    elif state.get("responding") is False:
        problems.append("sshd принимает подключение, но не отвечает (агент перезапускает его)")
    rule = state.get("firewall_rule")
    if rule in FIREWALL_RULE_LABELS:
        problems.append(f"правило брандмауэра для SSH с сервера: {FIREWALL_RULE_LABELS[rule]}")
    gpo = _gpo_blocks(state)
    if gpo:
        problems.append(
            "групповая политика игнорирует локальные правила брандмауэра (" + ", ".join(gpo)
            + ") и сама порт 22 не открывает — нужно правило в GPO"
        )
    if state.get("firewall_blocking"):
        problems.append("порт 22 закрыт правилом брандмауэра: " + "; ".join(state["firewall_blocking"]))
    if state.get("login_is_admin") is False:
        problems.append("учётная запись входа по SSH не в локальных Администраторах — ключ сервера для неё не действует")
    if state.get("domain_trust") == "broken":
        problems.append("нарушено доверие с доменом: вход доменной учёткой отклоняется (частая причина — второй ПК с тем же именем)")
    return problems


def ssh_problems(state: dict | None) -> list[str]:
    """Всё, что агент нашёл, — для карточки хоста (без учёта свежести)."""
    if not state:
        return []
    problems = _connection_problems(state)
    port = state.get("config_port")
    if port and port != 22:
        problems.append(f"sshd_config переносит SSH на порт {port}")
    if state.get("config_valid") is False:
        problems.append("sshd_config с ошибкой: после перезапуска sshd не запустится")
    if state.get("path_ok") is False:
        problems.append("в машинном PATH нет System32: Ansible не найдёт PowerShell")
    return problems


def ssh_blocked_reason(state: dict | None, now: datetime | None = None) -> str | None:
    """Почему SSH с сервера заведомо не сработает, по свежему отчёту агента; None — препятствий не видно."""
    if not _fresh(state, now):
        return None
    problems = _connection_problems(state)
    return "; ".join(problems) if problems else None


def host_keys(state: dict | None) -> list[str]:
    return list((state or {}).get("host_keys") or [])
