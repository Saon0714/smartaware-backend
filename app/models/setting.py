"""Runtime settings — the key/value store behind every configurable default."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import SettingValueType
from app.models.user import _enum


class Setting(TimestampMixin, UUIDPrimaryKeyMixin, Base):
    """A value SmartAWARE can change without a deploy.

    Every open question from spec Section 13 that needed a default is recorded
    here rather than in code, so revisiting a decision is an admin edit.
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    value_type: Mapped[SettingValueType] = mapped_column(
        _enum(SettingValueType, "setting_value_type"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    group: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    # False for values that must not be changed from the UI without care.
    is_editable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
