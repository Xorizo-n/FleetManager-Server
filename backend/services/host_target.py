from __future__ import annotations


def normalize_host_address(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def resolve_host_target(hostname: str | None, ip_address: str | None) -> str:
    normalized_hostname = normalize_host_address(hostname)
    normalized_ip = normalize_host_address(ip_address)
    # Prefer IP address when available — bypasses DNS resolution failures
    # for hosts on segments where the Fleet Manager's resolver doesn't have records.
    target = normalized_ip or normalized_hostname
    if target is None:
        raise ValueError('Необходимо указать имя хоста или IP-адрес')
    return target
