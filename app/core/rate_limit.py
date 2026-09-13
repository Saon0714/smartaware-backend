"""Rate limiting for unauthenticated endpoints.

The enquiry form is a public write endpoint, which makes it the obvious target
for abuse: spam submissions fill the Admin Portal and, once recipients are
configured, turn into a flood of email.

Redis-backed so the limit holds across multiple application instances — an
in-process counter would be trivially bypassed by whichever instance answered
next. If Redis is unavailable the limiter fails OPEN, because losing genuine
enquiries is worse than accepting some spam, and the honeypot still applies.
"""

from __future__ import annotations

import contextlib
import logging

from fastapi import Request

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None
_unavailable = False


def _redis():
    global _client, _unavailable
    if _unavailable:
        return None
    if _client is None:
        try:
            import redis

            _client = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=0.25)
            _client.ping()
        except Exception:
            logger.warning("Redis unavailable — rate limiting disabled.")
            _unavailable = True
            return None
    return _client


def client_ip(request: Request) -> str:
    """Best-effort caller identity.

    Behind a load balancer the socket address is the balancer, so the first
    X-Forwarded-For entry is used. That header is client-controlled, so this is
    a throttle, not an authorisation decision.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check(key: str, *, limit: int, window_seconds: int) -> bool:
    """True when the caller is within the limit."""
    connection = _redis()
    if connection is None:
        return True

    try:
        redis_key = f"ratelimit:{key}"
        count = connection.incr(redis_key)
        if count == 1:
            connection.expire(redis_key, window_seconds)
        return int(count) <= limit
    except Exception:
        logger.warning("Rate limit check failed — allowing request.", exc_info=True)
        return True


def reset(key: str) -> None:
    connection = _redis()
    if connection is not None:
        with contextlib.suppress(Exception):
            connection.delete(f"ratelimit:{key}")
