"""Smart AI conversation logs (spec Section 4.5)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ChatRole, ChatSurface
from app.models.user import _enum


class ChatSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Anonymous on the public site, attributed inside the portal.

    Transcripts are retained for a window configured in the `settings` table
    (default one month) and purged by a scheduled job — never a hardcoded
    constant, since spec 4.5 requires it to be admin-editable.
    """

    __tablename__ = "chat_sessions"

    session_token: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    surface: Mapped[ChatSurface] = mapped_column(_enum(ChatSurface, "chat_surface"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    messages: Mapped[list[ChatMessage]] = relationship(
        "ChatMessage", back_populates="session", cascade="all, delete-orphan"
    )


class ChatMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "chat_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[ChatRole] = mapped_column(_enum(ChatRole, "chat_role"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Recorded so the escalation threshold (Section 13 item 7, defaulted here)
    # can be tuned against real traffic instead of guessed at.
    escalated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    top_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    session: Mapped[ChatSession] = relationship("ChatSession", back_populates="messages")
