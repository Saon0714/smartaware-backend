"""Users and invites."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import InviteStatus, UserRole

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.service import ServiceCategory


#: The services an invited client is being signed up for.
#:
#: Chosen by the Admin when the invitation is issued and copied onto the client
#: record when it is redeemed. Kept on the invite rather than resolved at
#: redemption from anything the invitee supplies: what a client is engaged for
#: is a commercial decision, and nothing the person accepting the invitation
#: sends may influence it.
invite_services = Table(
    "invite_services",
    Base.metadata,
    Column(
        "invite_id",
        PgUUID(as_uuid=True),
        ForeignKey("invites.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "category_id",
        PgUUID(as_uuid=True),
        ForeignKey("service_categories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


def _enum(enum_cls: type, name: str) -> SAEnum:
    """Postgres native enum storing the member *values*, not their names."""
    return SAEnum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(_enum(UserRole, "user_role"), nullable=False)

    # Staff enable/disable. For clients, login is additionally gated on
    # Client.status (hold/deactive) — see auth_service.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Section 13 item 11 (MFA) is unconfirmed. The columns exist from the first
    # migration so enabling TOTP later needs no migration; enforcement is
    # driven by the `mfa_required_roles` DB setting and is off by default.
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Bumped to invalidate every outstanding token for this user at once:
    # password change, or an Admin putting the account on Hold/Deactive.
    # Tokens carry the version they were minted with and are rejected once
    # it no longer matches, so revocation does not need a session table.
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # The foreign key is ON DELETE CASCADE, so the ORM must be told as much.
    # Without this it tries to null clients.user_id on delete and fails against
    # a NOT NULL column — a confusing IntegrityError in place of a cascade.
    client: Mapped[Client | None] = relationship(
        "Client",
        back_populates="user",
        foreign_keys="Client.user_id",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Invite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Invite-only sign-up (spec Section 5.1).

    Single-use and expiring. Only a hash of the token is stored, so a database
    disclosure cannot be replayed into account creation — the raw token exists
    only in the emailed link.
    """

    __tablename__ = "invites"

    email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        _enum(UserRole, "user_role"), default=UserRole.CLIENT, nullable=False
    )
    status: Mapped[InviteStatus] = mapped_column(
        _enum(InviteStatus, "invite_status"), default=InviteStatus.PENDING, nullable=False
    )

    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Pre-filled onto the Client record on acceptance, so Admin can invite a
    # named company rather than a bare email address.
    prefill_company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    #: Copied onto the Client on acceptance. See `invite_services`.
    services: Mapped[list[ServiceCategory]] = relationship(
        "ServiceCategory", secondary=invite_services, lazy="selectin"
    )
