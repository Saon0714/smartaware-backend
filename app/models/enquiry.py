"""Public website enquiry submissions (spec Section 3.2)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Enquiry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Because the field list is admin-editable, the full submission is kept in
    `payload`. The handful of columns alongside it are denormalised copies of
    the fields the Admin Portal lists and searches on — they are conveniences,
    and `payload` remains the complete record even after fields change.
    """

    __tablename__ = "enquiries"

    form_key: Mapped[str] = mapped_column(String(64), default="enquiry", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    country: Mapped[str | None] = mapped_column(String(128), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service_required: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_handled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    internal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
