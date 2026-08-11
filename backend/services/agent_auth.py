import hashlib
import secrets


def issue_agent_token() -> str:
    return secrets.token_urlsafe(48)


def hash_agent_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_agent_token(token: str, token_hash: str) -> bool:
    return secrets.compare_digest(hash_agent_token(token), token_hash)
