import hashlib
import secrets
from datetime import datetime, timedelta


def issue_agent_token() -> str:
    return secrets.token_urlsafe(48)


def hash_agent_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_agent_token(token: str, token_hash: str) -> bool:
    return secrets.compare_digest(hash_agent_token(token), token_hash)


# How long after its last heartbeat a host still counts as alive when another PC
# registers with its machine id: a bit more than two default sync intervals (5 min).
CLONE_GUARD_WINDOW = timedelta(minutes=15)


def _short_name(hostname: str) -> str:
    return hostname.strip().split(".", 1)[0].lower()


def is_machine_id_clone(
    host_hostname: str | None,
    host_last_seen_at: datetime | None,
    registering_hostname: str | None,
    now: datetime,
) -> bool:
    """A registration that reuses the machine id of another host that is still reporting.

    PCs deployed from one image without sysprep can carry the same agent machine-id.
    Re-registering would hand the existing host to the new PC and silently invalidate
    the other PC's agent token, so the two would keep taking the host from each other.
    The same PC re-registering (same name) or a host that has gone quiet is allowed.
    """
    if not host_hostname or not registering_hostname:
        return False
    if _short_name(host_hostname) == _short_name(registering_hostname):
        return False
    return host_last_seen_at is not None and now - host_last_seen_at < CLONE_GUARD_WINDOW
