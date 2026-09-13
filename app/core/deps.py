"""Shared FastAPI dependencies.

Route handlers declare what they require — a session, a role, a permission —
and these dependencies enforce it. Nothing here trusts a claim in the token
alone: the user is always re-read from the database so revocation and account
status take effect immediately.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.permissions import ClientScope, Permission, has_permission, resolve_client_scope
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.services.auth_service import AccountBlockedError, AuthError, user_from_token

DbSession = Annotated[Session, Depends(get_db)]

# auto_error=False so a missing header yields our own 401 with a useful body
# rather than FastAPI's bare 403.
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return user_from_token(db, credentials.credentials, expected_type="access")
    except AccountBlockedError as exc:
        # 403, not 401: the credentials were fine, the account is barred. A 401
        # would send the client into a pointless re-login loop.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: UserRole) -> Callable[..., User]:
    """Restrict an endpoint to specific roles."""

    def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return user

    return dependency


def require_permission(permission: Permission) -> Callable[..., User]:
    """Restrict an endpoint to holders of a specific permission.

    Preferred over `require_role` wherever a rule is setting-dependent, since
    the matrix consults those settings rather than assuming a fixed role.
    """

    def dependency(user: CurrentUser, db: DbSession) -> User:
        if not has_permission(db, user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return user

    return dependency


RequireAdmin = Annotated[User, Depends(require_role(UserRole.ADMIN))]
RequireStaff = Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.MANAGER))]


def get_client_scope(user: CurrentUser, db: DbSession) -> ClientScope:
    """The set of clients the caller may read or write.

    Every query over client-owned data must be constrained with this. It is a
    dependency so an endpoint cannot forget to build one and accidentally run
    unscoped.
    """
    return resolve_client_scope(db, user)


CallerClientScope = Annotated[ClientScope, Depends(get_client_scope)]


def get_refresh_token(request: Request) -> str:
    """Read the refresh token from its httpOnly cookie.

    Never accepted from a header or body: the cookie is the only channel the
    page's JavaScript cannot read, which is the entire reason for using one.
    """
    from app.core.config import settings

    token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No active session")
    return token
