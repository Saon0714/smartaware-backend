"""Invite-only account creation — spec Section 5.1.

There is no public sign-up. An Admin issues an invite against an email address;
the emailed link carries a single-use token that expires after a configurable
window (default three days, held in the `settings` table).

Only a hash of the token is stored. The raw value exists in the email and
nowhere else, so a database disclosure cannot be replayed into account creation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    generate_client_ref,
    generate_token,
    hash_password,
    hash_token,
)
from app.core.settings_service import SettingKey, get_setting
from app.models.client import Client
from app.models.enums import InviteStatus, UserRole
from app.models.service import ServiceCategory
from app.models.user import Invite, User
from app.services.notification import NotificationEvent, notify


class InviteError(Exception):
    """Invite could not be issued or redeemed. Message is caller-safe."""


def _now() -> datetime:
    return datetime.now(UTC)


def _as_aware(value: datetime) -> datetime:
    """Postgres returns timezone-aware values; be tolerant of naive ones."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def effective_status(invite: Invite) -> InviteStatus:
    """Status including expiry, which is derived rather than stored.

    A row is not rewritten the moment it expires — nothing would trigger that —
    so expiry is computed on read and the stored value only records the
    terminal states someone actively caused.
    """
    if invite.status in (InviteStatus.USED, InviteStatus.REVOKED):
        return invite.status
    if _as_aware(invite.expires_at) <= _now():
        return InviteStatus.EXPIRED
    return InviteStatus.PENDING


def build_invite_url(token: str) -> str:
    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}/invite/{token}"


def resolve_services(
    db: Session, service_ids: list[uuid.UUID] | None
) -> list[ServiceCategory]:
    """Turn caller-supplied category IDs into rows, rejecting anything unknown.

    Duplicates collapse — asking for the same service twice is a request for
    that service, and the join table could not store it anyway.

    Archived categories are refused here, unlike when editing an existing
    client. Somebody being signed up now cannot be sold something SmartAWARE has
    withdrawn; an existing client may perfectly well still be engaged for one.
    """
    wanted = list(dict.fromkeys(service_ids or []))
    if not wanted:
        return []

    found = {
        category.id: category
        for category in db.execute(
            select(ServiceCategory).where(ServiceCategory.id.in_(wanted))
        ).scalars()
    }
    missing = [str(i) for i in wanted if i not in found]
    if missing:
        raise InviteError(f"Unknown service: {', '.join(missing)}.")

    archived = [found[i].name for i in wanted if found[i].is_archived]
    if archived:
        raise InviteError(f"This service is no longer offered: {', '.join(archived)}.")

    return [found[i] for i in wanted]


def create_invite(
    db: Session,
    *,
    email: str,
    invited_by: User,
    role: UserRole = UserRole.CLIENT,
    company_name: str | None = None,
    service_ids: list[uuid.UUID] | None = None,
) -> tuple[Invite, str]:
    """Issue an invite. Returns the row and the raw token (shown once)."""
    email = email.strip().lower()

    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise InviteError("An account with this email address already exists.")

    if role is UserRole.ADMIN and not get_setting(db, SettingKey.ALLOW_MULTIPLE_ADMINS, False):
        raise InviteError(
            "Additional Admin accounts are disabled. Enable 'allow_multiple_admins' first."
        )

    # Supersede any outstanding invite for this address so only the newest
    # link works — otherwise resending would leave earlier links live.
    for existing in db.execute(
        select(Invite).where(Invite.email == email, Invite.status == InviteStatus.PENDING)
    ).scalars():
        existing.status = InviteStatus.REVOKED
        existing.revoked_at = _now()

    services = resolve_services(db, service_ids)
    if services and role is not UserRole.CLIENT:
        # Only a client has services. Attaching them to a staff invite would
        # store a choice that redemption then silently discards.
        raise InviteError("Only client invitations can have services.")

    expiry_days = int(get_setting(db, SettingKey.INVITE_EXPIRY_DAYS, 3))
    raw_token = generate_token()

    invite = Invite(
        email=email,
        token_hash=hash_token(raw_token),
        role=role,
        status=InviteStatus.PENDING,
        invited_by_id=invited_by.id,
        expires_at=_now() + timedelta(days=expiry_days),
        prefill_company_name=company_name,
        services=services,
    )
    db.add(invite)
    db.flush()

    notify(
        db,
        NotificationEvent.INVITE_SENT,
        {
            "invite_url": build_invite_url(raw_token),
            "expiry_days": expiry_days,
            "portal_name": "Client Portal" if role is UserRole.CLIENT else "Staff Portal",
        },
        to=email,
    )
    return invite, raw_token


def get_invite_by_token(db: Session, raw_token: str) -> Invite:
    invite = db.execute(
        select(Invite).where(Invite.token_hash == hash_token(raw_token))
    ).scalar_one_or_none()
    if invite is None:
        raise InviteError("This invitation link is not valid.")
    return invite


def validate_token(db: Session, raw_token: str) -> Invite:
    """Return a redeemable invite, or raise with a specific reason.

    Section 5.1 asks for a clear error state, so expired, already-used and
    revoked are reported distinctly — the user needs to know whether to ask for
    a new link or simply sign in.
    """
    invite = get_invite_by_token(db, raw_token)
    status = effective_status(invite)

    if status is InviteStatus.USED:
        raise InviteError("This invitation has already been used. Please sign in instead.")
    if status is InviteStatus.REVOKED:
        raise InviteError("This invitation has been cancelled. Please contact SmartAWARE.")
    if status is InviteStatus.EXPIRED:
        raise InviteError("This invitation has expired. Please ask SmartAWARE to send a new one.")
    return invite


def accept_invite(
    db: Session, *, raw_token: str, password: str, full_name: str | None = None
) -> User:
    """Redeem an invite, creating the user and, for clients, their profile."""
    invite = validate_token(db, raw_token)

    if db.execute(select(User).where(User.email == invite.email)).scalar_one_or_none():
        raise InviteError("An account with this email address already exists.")

    user = User(
        email=invite.email,
        full_name=full_name,
        hashed_password=hash_password(password),
        role=invite.role,
        is_active=True,
    )
    db.add(user)
    db.flush()

    if user.role is UserRole.CLIENT:
        db.add(
            Client(
                user_id=user.id,
                client_ref=generate_client_ref(),
                company_name=invite.prefill_company_name,
                contact_email=user.email,
                # Taken from the invitation, not from the request. The person
                # signing up has no say in what they are engaged for, and no
                # field they submit reaches this — which is the point.
                services=list(invite.services),
            )
        )

    invite.status = InviteStatus.USED
    invite.used_at = _now()
    db.flush()
    return user


def revoke_invite(db: Session, invite_id: uuid.UUID) -> Invite:
    invite = db.get(Invite, invite_id)
    if invite is None:
        raise InviteError("Invitation not found.")
    if effective_status(invite) is InviteStatus.USED:
        raise InviteError("This invitation has already been used and cannot be revoked.")
    invite.status = InviteStatus.REVOKED
    invite.revoked_at = _now()
    db.flush()
    return invite
