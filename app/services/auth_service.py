"""Authentication: credential checks, token issuance and account gating.

All login gating lives here rather than in the route handler, so every entry
point — login, refresh, and each authenticated request — applies the same rules.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import (
    TokenError,
    create_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.models.client import Client
from app.models.enums import ClientStatus, UserRole
from app.models.user import User


class AuthError(Exception):
    """Authentication failed. The message is safe to return to the caller."""


class AccountBlockedError(AuthError):
    """The credentials were correct but the account may not hold a session."""


def _generic_failure() -> AuthError:
    """One message for "no such user" and "wrong password" alike, so the
    response cannot be used to discover which addresses have accounts."""
    return AuthError("Incorrect email or password")


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.execute(select(User).where(User.email == email.strip().lower())).scalar_one_or_none()


def assert_account_may_hold_session(db: Session, user: User) -> None:
    """Spec Sections 6.2 and 5.1.

    Hold and Deactive both block login. They are distinguished only by business
    meaning — a pause versus an ended relationship — so they map to identical
    access behaviour here and differ only in what Admin sees when reporting.

    Checked on login AND on every authenticated request, so an Admin placing a
    client on Hold cuts off an already-issued access token immediately rather
    than at its next expiry.
    """
    if not user.is_active:
        raise AccountBlockedError("This account has been deactivated.")

    if user.role is not UserRole.CLIENT:
        return

    client = db.execute(select(Client).where(Client.user_id == user.id)).scalar_one_or_none()
    if client is None:
        return

    if client.status is ClientStatus.HOLD:
        raise AccountBlockedError("Your account is currently on hold. Please contact SmartAWARE.")
    if client.status is ClientStatus.DEACTIVE:
        raise AccountBlockedError("This account is no longer active. Please contact SmartAWARE.")


def authenticate(db: Session, email: str, password: str) -> User:
    user = get_user_by_email(db, email)

    if user is None or not user.hashed_password:
        # Still spend the cost of a hash so a missing account cannot be
        # distinguished from a wrong password by response timing.
        verify_password(password, hash_password("timing-equalisation"))
        raise _generic_failure()

    if not verify_password(password, user.hashed_password):
        raise _generic_failure()

    assert_account_may_hold_session(db, user)

    if needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(password)

    user.last_login_at = datetime.now(UTC)
    db.flush()
    return user


def issue_tokens(user: User) -> tuple[str, str]:
    """Return (access_token, refresh_token)."""
    access = create_token(user.id, "access", user.token_version, role=user.role.value)
    refresh = create_token(user.id, "refresh", user.token_version)
    return access, refresh


def user_from_token(db: Session, token: str, expected_type: str = "access") -> User:
    """Resolve a token to a live user, re-checking every gate.

    The token is never trusted on its own: the user is loaded from the database
    so deactivation, Hold/Deactive status and token revocation all take effect
    at once rather than when the token happens to expire.
    """
    try:
        payload = decode_token(token, expected_type)  # type: ignore[arg-type]
    except TokenError as exc:
        raise AuthError(str(exc)) from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, KeyError) as exc:
        raise AuthError("Token is invalid") from exc

    user = db.get(User, user_id)
    if user is None:
        raise AuthError("Token is invalid")

    # Account status is checked first on purpose. Placing a client on Hold also
    # bumps their token version, so both gates trip at once — and "your account
    # is on hold" tells them something they can act on, where "session revoked"
    # would just send them to a login screen that then refuses them anyway.
    assert_account_may_hold_session(db, user)

    if payload.get("ver") != user.token_version:
        raise AuthError("Session has been revoked. Please sign in again.")

    return user


def revoke_all_sessions(db: Session, user: User) -> None:
    """Invalidate every outstanding token for this user."""
    user.token_version += 1
    db.flush()


def change_password(db: Session, user: User, current_password: str, new_password: str) -> None:
    if not user.hashed_password or not verify_password(current_password, user.hashed_password):
        raise AuthError("Current password is incorrect")

    user.hashed_password = hash_password(new_password)
    user.must_change_password = False
    # Signing out other devices is the expected consequence of a password
    # change, particularly if the reason was a suspected compromise.
    revoke_all_sessions(db, user)
