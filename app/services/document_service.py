"""Document upload, versioning and retrieval.

Spec Section 5.3.E covers documents a client sends in, 5.3.F those SmartAWARE
shares back, and Section 9 asks for encrypted storage plus audit logging of
uploads and downloads.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_service import SettingKey, get_setting
from app.models.document import Document
from app.models.enums import DocumentDirection, DocumentType
from app.models.user import User
from app.services import audit_service
from app.services.audit_service import AuditAction
from app.services.storage import build_key, get_storage, safe_filename

#: 25 MB. Tax documents are small; a larger ceiling mostly widens the window for
#: someone to fill the bucket. Raise it here if a client genuinely needs to.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

#: An allowlist, not a blocklist. Anything not named here is refused, so a new
#: dangerous type does not become acceptable by default.
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/heic",
    "image/tiff",
    "text/csv",
    "text/plain",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/zip",
}

#: Refused regardless of the declared content type, since the browser decides
#: what to do with a file by its extension.
BLOCKED_EXTENSIONS = {
    ".exe",
    ".dll",
    ".bat",
    ".cmd",
    ".com",
    ".scr",
    ".msi",
    ".jar",
    ".js",
    ".vbs",
    ".ps1",
    ".sh",
    ".app",
    ".dmg",
    ".html",
    ".htm",
    ".svg",
}


class DocumentError(Exception):
    """Upload or retrieval refused. The message is safe to show the caller."""


def validate_upload(filename: str, content_type: str | None, size: int) -> None:
    if size == 0:
        raise DocumentError("That file is empty.")
    if size > MAX_UPLOAD_BYTES:
        raise DocumentError(f"Files must be {MAX_UPLOAD_BYTES // (1024 * 1024)} MB or smaller.")

    cleaned = safe_filename(filename)
    extension = ("." + cleaned.rsplit(".", 1)[1].lower()) if "." in cleaned else ""
    if extension in BLOCKED_EXTENSIONS:
        raise DocumentError(f"Files of type {extension} cannot be uploaded.")

    if content_type and content_type.split(";")[0].strip() not in ALLOWED_CONTENT_TYPES:
        raise DocumentError(
            "That file type is not accepted. Please upload a PDF, image, spreadsheet or document."
        )


def _previous_version(
    db: Session, client_id: uuid.UUID, direction: DocumentDirection, file_name: str
) -> Document | None:
    return db.execute(
        select(Document)
        .where(
            Document.client_id == client_id,
            Document.direction == direction,
            Document.file_name == file_name,
            Document.is_archived.is_(False),
        )
        .order_by(Document.version.desc())
        .limit(1)
    ).scalar_one_or_none()


def store(
    db: Session,
    *,
    client_id: uuid.UUID,
    uploaded_by: User,
    direction: DocumentDirection,
    doc_type: DocumentType,
    filename: str,
    data: bytes,
    content_type: str | None,
) -> Document:
    """Store a file and record it.

    Re-uploading the same filename creates a new version by default rather than
    replacing the old one (Section 13 item 12). For tax records that is the
    safer default: an overwrite silently destroys the version someone may have
    already relied on.
    """
    validate_upload(filename, content_type, len(data))
    file_name = safe_filename(filename)

    previous = _previous_version(db, client_id, direction, file_name)
    keep_versions = get_setting(db, SettingKey.DOCUMENT_VERSIONING, "keep") == "keep"

    key = build_key(client_id, direction.value, file_name)
    storage = get_storage()
    stored = storage.put(key, data, content_type)

    document = Document(
        client_id=client_id,
        uploaded_by_id=uploaded_by.id,
        direction=direction,
        doc_type=doc_type,
        file_name=file_name,
        s3_key=stored.key,
        content_type=content_type,
        size_bytes=stored.size_bytes,
        version=(previous.version + 1) if previous else 1,
        supersedes_id=previous.id if previous else None,
    )
    db.add(document)

    if previous is not None and not keep_versions:
        # Archive the row and remove the object, so "overwrite" genuinely
        # discards the old file rather than leaving it billable and reachable.
        previous.is_archived = True
        storage.delete(previous.s3_key)

    db.flush()
    return document


def record_download(
    db: Session,
    *,
    document: Document,
    actor: User,
    ip_address: str | None = None,
) -> None:
    """Section 9 asks for document access to be logged, not just uploads."""
    audit_service.record(
        db,
        actor=actor,
        action=AuditAction.DOCUMENT_DOWNLOADED,
        entity_type="document",
        entity_id=document.id,
        new_value={
            "file_name": document.file_name,
            "client_id": str(document.client_id),
        },
        ip_address=ip_address,
    )


def superseded_ids(db: Session, client_id: uuid.UUID) -> set[uuid.UUID]:
    """Documents that a later version points back to."""
    rows = db.execute(
        select(Document.supersedes_id).where(
            Document.client_id == client_id, Document.supersedes_id.is_not(None)
        )
    ).scalars()
    return {row for row in rows if row is not None}


def counts_for(db: Session, scope) -> dict:
    stmt = select(Document).where(Document.is_archived.is_(False))
    stmt = scope.apply(stmt, Document.client_id)
    documents = list(db.execute(stmt).scalars())
    return {
        "from_client": sum(
            1 for d in documents if d.direction is DocumentDirection.CLIENT_TO_SMARTAWARE
        ),
        "from_smartaware": sum(
            1 for d in documents if d.direction is DocumentDirection.SMARTAWARE_TO_CLIENT
        ),
        "total": len(documents),
    }
