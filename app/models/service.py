"""Regions and the service taxonomy.

This taxonomy is the single source of truth for two consumers: the public
website's service pages, and the service categorisation on internal tasks.
Keeping one taxonomy means "what we advertise" and "what we deliver" cannot
drift apart.

Everything here is admin-managed at runtime — add, edit, reorder, publish,
unpublish and archive — with no code change and no deploy.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Region(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An operating market.

    A table, not an enum: the spec lists India/UAE/UK/GCC while the content
    brief lists UK/India/UAE/Oman. Rows mean reconciling that — or opening a
    new market — is data entry, not a migration.
    """

    __tablename__ = "regions"

    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # e.g. "UK Tax & Accounting Services" — the country page heading.
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # The form used inside a sentence: "Professional UK Tax & Compliance
    # Advisory". `name` is the formal one and reads badly there — "Professional
    # United Kingdom Tax..." — so the short form is its own field rather than
    # something derived. Falls back to `name` when unset.
    short_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    meta_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ServiceCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One of the top-level service categories shown on the website."""

    __tablename__ = "service_categories"

    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Spec 3.1 suggests 32-40 words. Enforced as a soft word-count hint in the
    # admin editor rather than a constraint: the supplied copy runs shorter,
    # and rejecting SmartAWARE's own approved wording would be wrong.
    short_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    long_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    icon_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cta_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cta_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Admin "delete" archives. Tasks reference categories, and destroying one
    # would corrupt the history of completed work.
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    meta_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    subcategories: Mapped[list[ServiceSubcategory]] = relationship(
        "ServiceSubcategory", back_populates="category", cascade="all, delete-orphan"
    )
    details: Mapped[list[ServiceDetail]] = relationship(
        "ServiceDetail", back_populates="category", cascade="all, delete-orphan"
    )


class ServiceSubcategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A specific deliverable within a category (e.g. "CIS Monthly Returns").

    Internal by default: these drive task categorisation rather than public
    pages. `is_published` exists so SmartAWARE can surface them on the website
    later without a schema change.
    """

    __tablename__ = "service_subcategories"
    __table_args__ = (UniqueConstraint("category_id", "slug", name="uq_subcategory_slug"),)

    category_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("service_categories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    category: Mapped[ServiceCategory] = relationship(
        "ServiceCategory", back_populates="subcategories"
    )


class ServiceDetail(UUIDPrimaryKeyMixin, Base):
    """A bullet under a category — the brief's "Suggested service details"."""

    __tablename__ = "service_details"

    category_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("service_categories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    category: Mapped[ServiceCategory] = relationship("ServiceCategory", back_populates="details")


class ServiceRegionAvailability(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Which categories are offered in which market, with optional overrides.

    A join rather than per-region service rows: a category is authored once and
    ticked per country, so editing "Bookkeeping" cannot leave four copies
    disagreeing. The content brief is explicit that a country page shows a
    service only once SmartAWARE confirms it applies there, which is exactly
    what `is_offered` records.

    Overrides handle local naming and wording — India's "VAT / GST Services"
    against the UK's "VAT Services" — without duplicating the category.
    """

    __tablename__ = "service_region_availability"
    __table_args__ = (UniqueConstraint("category_id", "region_id", name="uq_service_region"),)

    category_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("service_categories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    region_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("regions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_offered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    name_override: Mapped[str | None] = mapped_column(String(255), nullable=True)
    short_description_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    long_description_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class SubcategoryRegionAvailability(UUIDPrimaryKeyMixin, Base):
    """Optional per-market override for a single subcategory.

    Absence of a row means "inherit the parent category's availability", so the
    common case needs no rows at all. Rows appear only for genuine exceptions —
    CIS being UK-only, GST being India-only.
    """

    __tablename__ = "subcategory_region_availability"
    __table_args__ = (
        UniqueConstraint("subcategory_id", "region_id", name="uq_subcategory_region"),
    )

    subcategory_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("service_subcategories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    region_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("regions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_offered: Mapped[bool] = mapped_column(Boolean, nullable=False)
