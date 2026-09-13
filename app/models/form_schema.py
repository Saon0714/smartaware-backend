"""Database-driven form definitions.

Spec Section 13 leaves the enquiry form fields (item 1) and the client profile
fields (item 3) unconfirmed. Rather than guess and hardcode them, forms are
described by rows: SmartAWARE adds, removes, reorders and re-labels fields from
the Admin Portal, and the frontend renders whatever it is told.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import FormFieldType
from app.models.user import _enum


class FormDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "form_definitions"

    key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    fields: Mapped[list[FormField]] = relationship(
        "FormField",
        back_populates="form",
        cascade="all, delete-orphan",
        order_by="FormField.sort_order",
    )


class FormField(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "form_fields"
    __table_args__ = (UniqueConstraint("form_id", "key", name="uq_form_field_key"),)

    form_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("form_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    field_type: Mapped[FormFieldType] = mapped_column(
        _enum(FormFieldType, "form_field_type"), nullable=False
    )
    placeholder: Mapped[str | None] = mapped_column(String(255), nullable=True)
    help_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Choices for select/radio; validation rules (min, max, pattern).
    options: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    form: Mapped[FormDefinition] = relationship("FormDefinition", back_populates="fields")
