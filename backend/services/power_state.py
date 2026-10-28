"""Питание ПК по отчёту агента: когда загрузился, как закончилась прошлая работа, ставит ли обновления.

Половина ПК в офлайне уходит «молча» — агент не успевает сообщить о выключении (на 22.10–29.10
таких было 163 из 333). По журналу Windows (Kernel-Power 41, EventLog 6008, User32 1074) агент
после загрузки сообщает, что было: штатное выключение, перезагрузка, обесточивание или кнопка
питания, сбой Windows. Так отличается «выключили» от «пропал на ходу» — второе уже повод
разбираться с сетью или агентом.

Пока Windows ставит обновления, ожидающие задачи не выпускаются: установка закончится
перезагрузкой и оборвёт плейбук на середине («Data could not be sent to remote host»).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

FRESH_FOR = timedelta(minutes=20)
SHUTDOWN_LABELS = {
    "clean": "штатное выключение",
    "restart": "перезагрузка",
    "power_loss": "выключен кнопкой питания или обесточен",
    "crash": "сбой Windows",
    "unknown": "не определено",
}


def store_power_report(host, report, now: datetime) -> None:
    """report — schemas.agent.AgentPowerReport; None (старый агент) оставляет прежнее."""
    if report is None:
        return
    host.power_state = {**report.model_dump(mode="json"), "reported_at": now.isoformat()}


def updates_installing(state: dict | None, now: datetime | None = None) -> bool:
    if not state or not state.get("updates_installing"):
        return False
    try:
        reported = datetime.fromisoformat(state.get("reported_at") or "")
    except ValueError:
        return False
    return (now or datetime.now(timezone.utc)) - reported <= FRESH_FOR
