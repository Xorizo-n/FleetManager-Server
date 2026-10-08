"""Simple Redis-based rate limiter. No extra packages needed — uses the redis
client already in requirements.txt."""
import time

from redis import Redis

from config import settings

_redis: Redis | None = None


def _get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.celery_broker_url, decode_responses=True)
    return _redis


def check_rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    """Return True if the rate limit is exceeded (caller should 429).

    Uses a sliding-window counter in Redis DB 0 (same as Celery broker).
    Each key is namespaced with the current time window so it auto-expires.
    """
    r = _get_redis()
    bucket = f"rl:{key}:{int(time.time()) // window_seconds}"
    try:
        count = r.incr(bucket)
        if count == 1:
            r.expire(bucket, window_seconds * 2)
        return count > limit
    except Exception:
        # Redis unavailable — fail open (don't block legitimate users)
        return False
