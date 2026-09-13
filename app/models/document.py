"""Client and staff document exchange."""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import DocumentDirection, DocumentType
from app.models.user import _enum


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Spec Sections 5.3.E and 5.3.F.

    Section 13 item 12 (retention/versioning) is unconfirmed. Default chosen:
    keep versions, never overwrite — safer for tax records. A re-upload creates
    a new row pointing at the one it supersedes, so history stays intact.

    S3 keys are random and never exposed directly; downloads are served through
    short-lived presigned URLs issued only after a server-side scope check.
    """

    __tablename__ = "documents"

    client_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    direction: Mapped[DocumentDirection] = mapped_column(
        _enum(DocumentDirection, "document_direction"), nullable=False, index=True
    )
    doc_type: Mapped[DocumentType] = mapped_column(
        _enum(DocumentType, "document_type"), default=DocumentType.GENERAL, nullable=False
    )

    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
