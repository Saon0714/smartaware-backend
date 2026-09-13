"""Client work items."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import TaskStatus
from app.models.user import _enum


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Spec Sections 5.3.B and 6.3.

    Clients are strictly view-only. Managers may create, update and complete
    but never delete; only Admin may delete, and "delete" archives rather than
    destroying the row so completed work is never lost from a client's history.
    """

    __tablename__ = "tasks"

    client_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        _enum(TaskStatus, "task_status"), default=TaskStatus.PENDING, nullable=False, index=True
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Categorised against the same taxonomy the public website renders, so
    # "what we sell" and "what we do" never drift apart.
    service_category_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("service_categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    service_subcategory_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("service_subcategories.id", ondelete="SET NULL"),
        nullable=True,
    )

    assigned_manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Completion requires a note, and the timestamp is set server-side only —
    # spec 6.3 explicitly wants backdating to be impossible.
    completed_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
