"""Authentication endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, get_refresh_token
from app.core.permissions import effective_permissions
from app.models.client import Client
from app.schemas.auth import (
    AcceptInviteRequest,
    ChangePasswordRequest,
    ClientSummary,
    InviteCheckOut,
    LoginRequest,
    MeOut,
    MessageOut,
    ServiceRef,
    SessionOut,
    UserOut,
)
from app.services import auth_service, invite_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Attach the refresh token as an httpOnly cookie.

    httpOnly keeps it away from page JavaScript. SameSite=Lax is sufficient
    because production serves both apps from one registrable domain
    (app.* and api.*), which also makes them same-site for cookie purposes.
    """
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=token,
        max_age=settings.REFRESH_TOKEN_TTL_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        path="/",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        path="/",
    )


def _session_payload(user) -> SessionOut:
    access, _ = auth_service.issue_tokens(user)
    return SessionOut(
        access_token=access,
        expires_in=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=SessionOut, summary="Sign in")
def login(payload: LoginRequest, response: Response, db: DbSession) -> SessionOut:
    try:
        user = auth_service.authenticate(db, payload.email, payload.password)
    except auth_service.AccountBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    access, refresh = auth_service.issue_tokens(user)
    db.commit()

    _set_refresh_cookie(response, refresh)
    return SessionOut(
        access_token=access,
        expires_in=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/refresh", response_model=SessionOut, summary="Exchange refresh cookie")
def refresh(
    response: Response,
    db: DbSession,
    token: Annotated[str, Depends(get_refresh_token)],
) -> SessionOut:
    try:
        user = auth_service.user_from_token(db, token, expected_type="refresh")
    except auth_service.AccountBlockedError as exc:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except auth_service.AuthError as exc:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    access, new_refresh = auth_service.issue_tokens(user)
    db.commit()

    # Rotate on every use so a stolen cookie has a short useful life.
    _set_refresh_cookie(response, new_refresh)
    return SessionOut(
        access_token=access,
        expires_in=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/logout", response_model=MessageOut, summary="Sign out")
def logout(response: Response) -> MessageOut:
    _clear_refresh_cookie(response)
    return MessageOut(message="Signed out.")


@router.get("/me", response_model=MeOut, summary="Current user")
def me(user: CurrentUser, db: DbSession) -> MeOut:
    client = db.execute(select(Client).where(Client.user_id == user.id)).scalar_one_or_none()
    return MeOut(
        user=UserOut.model_validate(user),
        client=ClientSummary.model_validate(client) if client else None,
        permissions=sorted(effective_permissions(db, user)),
    )


@router.post("/change-password", response_model=MessageOut, summary="Change password")
def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    user: CurrentUser,
    db: DbSession,
) -> MessageOut:
    try:
        auth_service.change_password(db, user, payload.current_password, payload.new_password)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.commit()
    # Every session was just revoked, including this one.
    _clear_refresh_cookie(response)
    return MessageOut(message="Password changed. Please sign in again.")


# --- Invite redemption (public: the caller has no account yet) ----------------


@router.get(
    "/invite/{token}",
    response_model=InviteCheckOut,
    summary="Check an invitation link",
)
def check_invite(token: str, db: DbSession) -> InviteCheckOut:
    try:
        invite = invite_service.validate_token(db, token)
    except invite_service.InviteError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return InviteCheckOut(
        email=invite.email,
        role=invite.role,
        company_name=invite.prefill_company_name,
        expires_at=invite.expires_at,
        # Shown so the invitee knows what the account is being set up for. There
        # is no corresponding field on the accept request — what a client is
        # engaged for is SmartAWARE's decision, taken when the invitation was
        # issued.
        services=[ServiceRef.model_validate(s) for s in invite.services],
    )


@router.post(
    "/invite/{token}/accept",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account from an invitation",
)
def accept_invite(
    token: str, payload: AcceptInviteRequest, response: Response, db: DbSession
) -> SessionOut:
    try:
        user = invite_service.accept_invite(
            db, raw_token=token, password=payload.password, full_name=payload.full_name
        )
    except invite_service.InviteError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    access, refresh = auth_service.issue_tokens(user)
    db.commit()

    _set_refresh_cookie(response, refresh)
    return SessionOut(
        access_token=access,
        expires_in=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
        user=UserOut.model_validate(user),
    )
