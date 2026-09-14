"""SQLAlchemy declarative base and shared column mixins."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for every model."""


class UUIDPrimaryKeyMixin:
    """UUID primary keys.

    Deliberately not sequential integers. Client-scoped resources are addressed
    by ID in URLs, and sequential IDs invite enumeration attempts. Query-level
    scoping is still the actual defence (see `resolve_client_scope`) — this
    just removes the temptation to guess.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

