from __future__ import annotations


def normalize_host_address(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def resolve_host_target(hostname: str | None, ip_address: str | None) -> str:
    normalized_hostname = normalize_host_address(hostname)
    normalized_ip = normalize_host_address(ip_address)
    target = normalized_hostname or normalized_ip
    if target is None:
        raise ValueError("Необходимо указать имя хоста или IP-адрес")
    return target
