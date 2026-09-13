"""Admin-editable website content.

Everything the public site renders lives here, so SmartAWARE can change copy
without a developer or a deploy — the spec treats that as a hard architectural
constraint, not a convenience.

Two shapes are used deliberately:
  * structured tables for repeating, typed entities (team, milestones, values)
    where each record has real fields worth querying and ordering;
  * generic `ContentBlock` / `ContentListItem` for prose sections, so adding a
    paragraph to the About page never needs a new table.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ContentBlock(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named prose section, addressed by a stable key.

    Keys (e.g. `about_intro`, `vision`, `mission`, `home_hero`) are referenced
    by the frontend; the body behind them is fully editable.
    """

    __tablename__ = "content_blocks"

    key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subtitle: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ContentListItem(UUIDPrimaryKeyMixin, Base):
    """An ordered bullet belonging to a ContentBlock (mission points, etc.)."""

    __tablename__ = "content_list_items"

    block_key: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CoreValue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "core_values"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    icon_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class KeyStrength(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "key_strengths"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    icon_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Milestone(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Company timeline. The brief asks for this to stay extensible."""

    __tablename__ = "milestones"

    year_label: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class TeamMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Fields exactly as the content brief specifies.

    Seeded empty on purpose: real names, qualifications and photographs are
    SmartAWARE's to enter and verify.
    """

    __tablename__ = "team_members"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    designation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    qualifications: Mapped[str | None] = mapped_column(Text, nullable=True)
    areas_of_expertise: Mapped[str | None] = mapped_column(Text, nullable=True)
    professional_experience: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Qualification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Professional memberships and certifications.

    `is_verified` defaults to False and publication is gated on it, because the
    brief is explicit that only verified credentials may appear publicly.
    """

    __tablename__ = "qualifications"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    qualification_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Achievement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Headline statistics (clients served, returns completed, years active).

    Seeded empty: these are factual claims about the business and must come
    from SmartAWARE, not from a plausible-looking guess.
    """

    __tablename__ = "achievements"

    label: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(String(64), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Testimonial(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Seeded empty — inventing client quotes would be fabricating evidence."""

    __tablename__ = "testimonials"

    author_name: Mapped[str] = mapped_column(String(255), nullable=False)
    author_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class LegalPage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Privacy Policy, Cookie Policy, Terms.

    Seeded as clearly-marked placeholders. These are legal instruments that
    must reflect SmartAWARE's actual practices, so the text has to come from
    them or their advisers.
    """

    __tablename__ = "legal_pages"

    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ContactDetail(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Addresses, phone numbers, WhatsApp, email, hours, map link.

    Optionally scoped to a region so each market can show its own office.
    """

    __tablename__ = "contact_details"

    label: Mapped[str] = mapped_column(String(255), nullable=False)
    # address | phone | whatsapp | email | hours | map | department
    detail_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    region_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("regions.id", ondelete="SET NULL"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SocialLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "social_links"

    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
