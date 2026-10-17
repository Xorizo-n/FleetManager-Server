"""Сводный статус активации Windows и Office по снимку, который присылает агент.

Агент с версии 2026.10.17 раз в час читает SoftwareLicensingProduct, последнюю попытку
обращения к KMS из журнала и проверяет, открыт ли порт KMS (hosts.license_activation).
Реестр хостов, фильтр и выгрузка показывают по каждому виду продукта худшее состояние.
"""

LICENSED = "licensed"
# Активирован через KMS, но до истечения меньше EXPIRING_DAYS: продление (раз в 7 дней)
# давно не проходит — обычно KMS перестал быть доступен с ПК
EXPIRING = "expiring"
GRACE = "grace"
UNLICENSED = "unlicensed"

EXPIRING_DAYS = 30
KINDS = ("windows", "office")

# Чем хуже, тем больше
_SEVERITY = {LICENSED: 0, EXPIRING: 1, GRACE: 2, UNLICENSED: 3}
# SoftwareLicensingProduct.LicenseStatus: 2 — OOB grace, 3 — OOT grace, 4 — non-genuine grace, 6 — extended grace
_GRACE_STATUSES = {2, 3, 4, 6}

STATE_LABELS = {
    LICENSED: "активирован",
    EXPIRING: "активация истекает",
    GRACE: "пробный период",
    UNLICENSED: "не активирован",
}


def is_kms_client(product: dict) -> bool:
    description = product.get("description") or ""
    channel = product.get("channel") or ""
    return "VOLUME_KMSCLIENT" in description.upper() or channel.lower() == "volume:gvlk"


def product_state(product: dict) -> str:
    status = product.get("license_status")
    if status == 1:
        grace = product.get("grace_minutes") or 0
        if is_kms_client(product) and 0 < grace < EXPIRING_DAYS * 24 * 60:
            return EXPIRING
        return LICENSED
    if status in _GRACE_STATUSES:
        return GRACE
    return UNLICENSED


def activation_state(activation: dict | None, kind: str) -> str | None:
    """Худшее состояние продуктов вида kind; None — данных нет или продукт не установлен."""
    if not activation:
        return None
    states = [product_state(p) for p in activation.get("products") or [] if p.get("kind") == kind]
    return max(states, key=_SEVERITY.__getitem__) if states else None
