"""Password hashing and token generation primitives.

Argon2id via argon2-cffi rather than passlib, which is effectively unmaintained
and mis-handles bcrypt 4.x.
"""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    try:
        return _hasher.check_needs_rehash(hashed)
    except InvalidHashError:
        return True


def generate_token(length: int = 48) -> str:
    """A raw, URL-safe token. Returned to the caller once and never stored."""
    return secrets.token_urlsafe(length)


def hash_token(token: str) -> str:
    """Store only this.

    Invite tokens are bearer credentials. SHA-256 is right here rather than a
    slow KDF: the token already has full entropy, so there is nothing to brute
    force, and lookup happens on every invite acceptance.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_client_ref() -> str:
    """A short, non-sequential client reference.

    Never derived from a tax identifier — those are sensitive and must not end
    up in URLs, emails or logs.
    """
    return f"SA-{secrets.token_hex(4).upper()}"


# --- JWT ---------------------------------------------------------------------
#
# Access tokens are short-lived and held only in the frontend's memory. Refresh
# tokens are long-lived but travel in an httpOnly cookie, so page JavaScript --
# and therefore an XSS payload -- cannot read them. See BUILD_PLAN Q1.

import uuid  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402
from typing import Any, Literal  # noqa: E402

import jwt  # noqa: E402

from app.core.config import settings  # noqa: E402

TokenType = Literal["access", "refresh"]


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired or the wrong type."""


def create_token(
    subject: uuid.UUID,
    token_type: TokenType,
    token_version: int,
    role: str | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    now = datetime.now(UTC)
    if expires_delta is None:
        expires_delta = (
            timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES)
            if token_type == "access"
            else timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)
        )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "typ": token_type,
        "ver": token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": secrets.token_urlsafe(16),
    }
    if role is not None:
        payload["role"] = role
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """Decode and validate a token, or raise TokenError.

    The type is checked explicitly: a refresh token must never be accepted
    where an access token is expected, or its much longer lifetime would
    silently become the session length.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Token is invalid") from exc

    if payload.get("typ") != expected_type:
        raise TokenError(f"Expected a {expected_type} token")
    if not payload.get("sub"):
        raise TokenError("Token has no subject")
    return payload
