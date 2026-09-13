"""Document schemas — spec Sections 5.3.E and 5.3.F."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import DocumentDirection, DocumentType


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    direction: DocumentDirection
    doc_type: DocumentType
    file_name: str
    content_type: str | None
    size_bytes: int | None
    version: int
    supersedes_id: uuid.UUID | None
    created_at: datetime

    uploaded_by_name: str | None = None
    #: True when a newer version of the same filename exists.
    is_superseded: bool = False


class StaffDocumentOut(DocumentOut):
    client_ref: str
    client_company_name: str | None
    uploaded_by_email: EmailStr | None = None
    is_archived: bool = False


class DownloadOut(BaseModel):
    """Either a signed URL, or a flag telling the caller to stream instead."""

    url: str | None
    file_name: str
    expires_in: int | None = None


class DocumentCounts(BaseModel):
    from_client: int
    from_smartaware: int
    total: int


class DocumentNote(BaseModel):
    """Optional free text accompanying an upload."""

    note: str | None = Field(default=None, max_length=1000)
