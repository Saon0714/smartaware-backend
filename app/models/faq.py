"""FAQ content and its vector index (spec Section 4)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FaqEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One flat FAQ pool — not segmented by country or service (spec 4.1).

    The nightly re-index is incremental (spec 4.4), and these three columns are
    what make that possible: compare `updated_at` against `indexed_at` to find
    new or edited entries, and use the soft-delete flag to find embeddings that
    must be removed. A full re-embed of the pool is explicitly not acceptable.
    """

    __tablename__ = "faq_entries"

    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Soft delete so the indexer can retire the matching embeddings on its next
    # run rather than leaving them orphaned in the vector table.
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    embeddings: Mapped[list[FaqEmbedding]] = relationship(
        "FaqEmbedding", back_populates="faq", cascade="all, delete-orphan"
    )


class FaqEmbedding(UUIDPrimaryKeyMixin, Base):
    """A vector for one chunk of an FAQ entry, in the same Postgres instance."""

    __tablename__ = "faq_embeddings"
    # Declared here as well as in the migration so Alembic's autogenerate
    # sees it in the metadata and does not propose dropping it. Cosine
    # distance matches what the escalation threshold compares against.
    __table_args__ = (
        Index(
            "ix_faq_embeddings_vector",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    faq_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("faq_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.OPENAI_EMBEDDING_DIMENSIONS), nullable=False
    )
    # Recorded so a model change can be detected and re-embedded selectively.
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    faq: Mapped[FaqEntry] = relationship("FaqEntry", back_populates="embeddings")
