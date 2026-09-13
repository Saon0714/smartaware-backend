"""Invite management — spec Section 6.2.

Admin-only. Listing, revoking and resending are here; the redemption endpoints
the invited person uses live under /auth, since they have no account yet.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import DbSession, RequireAdmin
from app.models.enums import InviteStatus
from app.models.user import Invite
from app.schemas.auth import InviteCreatedOut, InviteCreateRequest, InviteOut
from app.services import invite_service

router = APIRouter(prefix="/admin/invites", tags=["admin-invites"])


def _to_out(invite: Invite) -> InviteOut:
    """Serialise with the *derived* status so an expired invite reads as
    expired even though nothing rewrote the row when it lapsed."""
    data = InviteOut.model_validate(invite)
    return data.model_copy(update={"status": invite_service.effective_status(invite)})


@router.post(
    "",
    response_model=InviteCreatedOut,
    status_code=status.HTTP_201_CREATED,
    summary="Send an invitation",
)
def create_invite(
    payload: InviteCreateRequest, admin: RequireAdmin, db: DbSession
) -> InviteCreatedOut:
    try:
        invite, raw_token = invite_service.create_invite(
            db,
            email=payload.email,
            invited_by=admin,
            role=payload.role,
            company_name=payload.company_name,
            service_ids=payload.service_ids,
        )
    except invite_service.InviteError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.commit()
    db.refresh(invite)

    return InviteCreatedOut(
        invite=_to_out(invite),
        # Returned outside production so the flow is testable without a mail
        # server. Leaking a live invite link through an API response would
        # hand anyone who can read it a working account-creation token.
        invite_url=None if settings.is_production else invite_service.build_invite_url(raw_token),
    )


@router.get("", response_model=list[InviteOut], summary="List invitations")
def list_invites(
    admin: RequireAdmin,
    db: DbSession,
    status_filter: Annotated[InviteStatus | None, Query(alias="status")] = None,
) -> list[InviteOut]:
    invites = db.execute(select(Invite).order_by(Invite.created_at.desc())).scalars().all()
    results = [_to_out(i) for i in invites]
    if status_filter is not None:
        results = [i for i in results if i.status == status_filter]
    return results


@router.post("/{invite_id}/revoke", response_model=InviteOut, summary="Revoke an invitation")
def revoke_invite(invite_id: uuid.UUID, admin: RequireAdmin, db: DbSession) -> InviteOut:
    try:
        invite = invite_service.revoke_invite(db, invite_id)
    except invite_service.InviteError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(invite)
    return _to_out(invite)


@router.post(
    "/{invite_id}/resend",
    response_model=InviteCreatedOut,
    summary="Resend an invitation",
)
def resend_invite(invite_id: uuid.UUID, admin: RequireAdmin, db: DbSession) -> InviteCreatedOut:
    """Issue a fresh link. The previous one is revoked, so only the newest
    link works — resending must not leave earlier links live."""
    existing = db.get(Invite, invite_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found.")

    try:
        invite, raw_token = invite_service.create_invite(
            db,
            email=existing.email,
            invited_by=admin,
            role=existing.role,
            company_name=existing.prefill_company_name,
            # The new link must stand for the same offer as the old one.
            service_ids=[service.id for service in existing.services],
        )
    except invite_service.InviteError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.commit()
    db.refresh(invite)
    return InviteCreatedOut(
        invite=_to_out(invite),
        invite_url=None if settings.is_production else invite_service.build_invite_url(raw_token),
    )
