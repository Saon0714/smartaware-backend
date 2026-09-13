"""Client business profiles."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ClientStatus
from app.models.service import ServiceCategory
from app.models.user import User, _enum

#: Which services a client is engaged for.
#:
#: A separate table rather than a column: a client commonly takes several
#: (payroll and VAT and year-end accounts is an ordinary combination), and the
#: admin list has to be able to filter on one without a client appearing once
#: per service. It points at the same taxonomy the website and tasks use, so
#: "what we sell", "what this client buys" and "what we are working on" cannot
#: drift apart.
#:
#: Deleting a client removes its rows. Deleting a category does too — but the
#: Admin Portal archives categories rather than deleting them precisely because
#: history depends on them, so in practice a link outlives an archived service.
client_services = Table(
    "client_services",
    Base.metadata,
    Column(
        "client_id",
        PgUUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "category_id",
        PgUUID(as_uuid=True),
        ForeignKey("service_categories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    # The composite primary key already indexes client-first lookups ("what does
    # this client take?"). The admin list filters the other way round — "who
    # takes payroll?" — which that index cannot serve.
    Index("ix_client_services_category_id", "category_id"),
)


class Client(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A client account (spec Section 5.3.A, Section 8).

    Profile fields are Section 13 item 3 — unconfirmed. The stable identity
    fields are real columns; anything SmartAWARE later adds from the Admin
    Portal lands in `extra`, driven by the `client_profile` form definition. So
    adding a profile field needs no migration and no deploy.
    """

    __tablename__ = "clients"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    # Human-facing reference. Random, never derived from a tax identifier.
    client_ref: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)

    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_registration_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    registration_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    region_or_county: Mapped[str | None] = mapped_column(String(128), nullable=True)
    postcode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    country: Mapped[str | None] = mapped_column(String(128), nullable=True)

    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[ClientStatus] = mapped_column(
        _enum(ClientStatus, "client_status"),
        default=ClientStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    status_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    assigned_manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    #: Ordered by the taxonomy's own order so a client's services read in the
    #: same sequence everywhere they are listed.
    services: Mapped[list[ServiceCategory]] = relationship(
        "ServiceCategory",
        secondary=client_services,
        order_by=(ServiceCategory.sort_order, ServiceCategory.name),
        lazy="selectin",
    )

    user: Mapped[User] = relationship("User", back_populates="client", foreign_keys=[user_id])
    assigned_manager: Mapped[User | None] = relationship("User", foreign_keys=[assigned_manager_id])
