from __future__ import annotations


def format_stage(stage: str, message: str, *, ok: bool | None = None) -> str:
    marker = "OK" if ok is True else "FAIL" if ok is False else "INFO"
    return f"[{marker}] {stage}: {message}"


def inventory_host_key(host_id: object) -> str:
    return str(host_id)


def sanitize_detail(detail: str, secrets: list[str] | tuple[str, ...] = ()) -> str:
    sanitized = str(detail)
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    return sanitized[:1000]
