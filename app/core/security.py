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
