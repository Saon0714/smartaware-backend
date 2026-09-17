"""remove chat transcripts

Revision ID: 2f5b90c41d63
Revises: 4a7c02e9b118
Create Date: 2026-09-17 20:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2f5b90c41d63"
down_revision: str | None = "4a7c02e9b118"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Stop keeping a record of what people ask Smart AI, and erase the ones held.

    Every question anyone typed into the widget was stored, attributed to their
    account when they were signed in, and readable in the Admin Portal. What
    someone asks a chatbot about their own tax affairs is personal data they
    never offered to SmartAWARE — they asked a question, they did not make a
    disclosure. SmartAWARE's decision is that it should not be kept at all.

    This drops the transcripts rather than hiding them: erasure is the point,
    so the rows go and the tables with them. The two settings that governed
    retention and who could read a transcript go too, because neither has
    anything left to govern.

    The chatbot itself is unaffected. It answers from the FAQ as it did, with
    the conversation held in the asker's own browser. A person who wants
    SmartAWARE to see their question sends an enquiry, which is deliberate and
    has a form in front of them.

    Irreversible by design. `downgrade` rebuilds the tables so the schema can
    be stepped back, but the transcripts are gone for good.
    """
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")

    sa.Enum(name="chat_role").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="chat_surface").drop(op.get_bind(), checkfirst=True)

    op.execute(
        sa.text(
            "DELETE FROM settings WHERE key IN ('chat_retention_days', 'chat_logs_visible_to')"
        )
    )


def downgrade() -> None:
    """Restores the shape, never the contents."""
    # Left for create_table to emit: naming the type and creating it here as
    # well makes Postgres see the CREATE TYPE twice.
    chat_role = sa.Enum("user", "assistant", name="chat_role")
    chat_surface = sa.Enum("public", "portal", name="chat_surface")

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_token", sa.String(length=128), nullable=False),
        sa.Column("surface", chat_surface, nullable=False),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "client_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_chat_sessions_session_token", "chat_sessions", ["session_token"], unique=True
    )
    op.create_index("ix_chat_sessions_last_activity_at", "chat_sessions", ["last_activity_at"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", chat_role, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("escalated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("top_similarity", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])
