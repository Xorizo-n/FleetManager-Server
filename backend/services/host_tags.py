"""Теги хостов по производителю и модели.

Тег — роль ПК («Студенты», «Семинарские», «Администрация»), по которой удобно выбирать цели
плейбуков. У ПК один тег: роль у компьютера одна, а с одним тегом однозначно, что делает
правило и что — ручная правка. Правило «производитель + модель → тег» ставит тег всем ПК без
ручного тега: при каждом heartbeat и сразу после изменения правил. Ручной тег (в том числе
ручное «без тега») правила не трогают, пока его не вернут «по правилу».
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.host import Host, HostTagRule


def model_key(manufacturer: str | None, model: str | None) -> tuple[str, str] | None:
    """Ключ сравнения: без регистра и лишних пробелов. None — агент не прислал модель."""
    manufacturer = " ".join((manufacturer or "").split()).casefold()
    model = " ".join((model or "").split()).casefold()
    if not manufacturer or not model:
        return None
    return manufacturer, model


def rule_map(rules) -> dict[tuple[str, str], uuid.UUID]:
    return {key: rule.tag_id for rule in rules if (key := model_key(rule.manufacturer, rule.model))}


def load_rule_map(db: Session) -> dict[tuple[str, str], uuid.UUID]:
    return rule_map(db.execute(select(HostTagRule)).scalars().all())


def rule_tag(rules: dict, manufacturer: str | None, model: str | None) -> uuid.UUID | None:
    key = model_key(manufacturer, model)
    return rules.get(key) if key else None


def apply_rule(host: Host, rules: dict) -> bool:
    """Ставит ПК тег по правилу, если тег не ручной. True — тег изменился."""
    if host.tag_manual:
        return False
    tag_id = rule_tag(rules, host.hw_manufacturer, host.hw_model)
    if host.tag_id == tag_id:
        return False
    host.tag_id = tag_id
    return True


def retag_hosts(db: Session) -> int:
    """Пересчитывает теги всех ПК без ручного тега (после изменения правил). Возвращает,
    у скольких ПК тег изменился; commit — за вызывающим."""
    rules = load_rule_map(db)
    hosts = db.execute(select(Host).where(Host.tag_manual.is_(False))).scalars().all()
    return sum(1 for host in hosts if apply_rule(host, rules))
