"""Client portal: documents — spec Sections 5.3.E and 5.3.F.

Clients may upload their own documents and download both what they sent and
what SmartAWARE shared with them. Every query is scope-constrained, so a client
reaches their own records and nobody else's.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import CallerClientScope, CurrentUser, DbSession
from app.core.rate_limit import client_ip
from app.models.document import Document
from app.models.enums import DocumentDirection, DocumentType
from app.models.user import User
from app.schemas.document import DocumentCounts, DocumentOut, DownloadOut
from app.services import document_service
from app.services.notification import NotificationEvent, dispatch, prepare
from app.services.storage import StorageError, get_storage

router = APIRouter(prefix="/portal", tags=["portal-documents"])


def _serialise(db: Session, document: Document, superseded: set) -> dict:
    uploader = db.get(User, document.uploaded_by_id) if document.uploaded_by_id else None
    return {
        "id": document.id,
        "client_id": document.client_id,
        "direction": document.direction,
        "doc_type": document.doc_type,
        "file_name": document.file_name,
        "content_type": document.content_type,
        "size_bytes": document.size_bytes,
        "version": document.version,
        "supersedes_id": document.supersedes_id,
        "created_at": document.created_at,
        "uploaded_by_name": ((uploader.full_name or uploader.email) if uploader else None),
        "is_superseded": document.id in superseded,
    }


def _load(db: Session, scope, document_id: uuid.UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.is_archived or not scope.allows(document.client_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return document


@router.get("/documents", response_model=list[DocumentOut], summary="My documents")
def my_documents(
    db: DbSession,
    scope: CallerClientScope,
    direction: Annotated[DocumentDirection | None, None] = None,
) -> Any:
    stmt = (
        select(Document).where(Document.is_archived.is_(False)).order_by(Document.created_at.desc())
    )
    stmt = scope.apply(stmt, Document.client_id)
    if direction is not None:
        stmt = stmt.where(Document.direction == direction)

    documents = list(db.execute(stmt).scalars())
    superseded = {d.supersedes_id for d in documents if d.supersedes_id is not None}
    return [_serialise(db, d, superseded) for d in documents]


@router.get("/documents/counts", response_model=DocumentCounts, summary="My document counts")
def my_document_counts(db: DbSession, scope: CallerClientScope) -> Any:
    return document_service.counts_for(db, scope)


@router.post(
    "/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document",
)
async def upload_document(
    user: CurrentUser,
    db: DbSession,
    scope: CallerClientScope,
    request: Request,
    file: Annotated[UploadFile, File()],
    doc_type: Annotated[DocumentType, Form()] = DocumentType.GENERAL,
) -> Any:
    """Spec 5.3.E.

    A client uploads only to their own account — the target is taken from their
    scope, never from the request, so there is no client_id to tamper with.
    """
    if len(scope.client_ids) != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a client account can upload here.",
        )
    client_id = next(iter(scope.client_ids))

    data = await file.read()
    try:
        document = document_service.store(
            db,
            client_id=client_id,
            uploaded_by=user,
            direction=DocumentDirection.CLIENT_TO_SMARTAWARE,
            doc_type=doc_type,
            filename=file.filename or "document",
            data=data,
            content_type=file.content_type,
        )
    except document_service.DocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    # Section 7 routes an invoice upload more narrowly than a general one: a
    # payment receipt needs the people who can reconcile it, not the whole team.
    event = (
        NotificationEvent.CLIENT_INVOICE_UPLOADED
        if doc_type is DocumentType.INVOICE
        else NotificationEvent.CLIENT_DOCUMENT_UPLOADED
    )
    client = user.client
    message = prepare(
        db,
        event,
        {
            "client_name": (client.company_name if client else None) or user.email,
            "file_name": document.file_name,
            "invoice_reference": "—",
            "admin_url": f"{settings.FRONTEND_BASE_URL.rstrip('/')}/admin/documents",
        },
        client_id=client_id,
    )
    db.commit()
    dispatch(message)

    db.refresh(document)
    return _serialise(db, document, set())


@router.get(
    "/documents/{document_id}/download",
    response_model=DownloadOut,
    summary="Get a download link",
)
def request_download(
    document_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    scope: CallerClientScope,
) -> Any:
    """Issue a short-lived link, after checking the caller may have it.

    The scope check happens here, not at the storage layer — a signed URL is
    only ever handed out for a document the caller has already been authorised
    to read.
    """
    document = _load(db, scope, document_id)
    document_service.record_download(
        db, document=document, actor=user, ip_address=client_ip(request)
    )
    db.commit()

    url = get_storage().download_url(
        document.s3_key,
        filename=document.file_name,
        expires_in=settings.S3_PRESIGNED_URL_TTL_SECONDS,
    )
    return DownloadOut(
        url=url,
        file_name=document.file_name,
        expires_in=settings.S3_PRESIGNED_URL_TTL_SECONDS if url else None,
    )


@router.get(
    "/documents/{document_id}/content",
    summary="Download the file",
    response_class=Response,
)
def download_content(
    document_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    scope: CallerClientScope,
) -> Response:
    """Stream the bytes.

    Used when the storage backend cannot issue a signed link, which is the case
    in local development. Authorisation is identical either way.
    """
    document = _load(db, scope, document_id)
    document_service.record_download(
        db, document=document, actor=user, ip_address=client_ip(request)
    )
    db.commit()

    try:
        data = get_storage().get(document.s3_key)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The file is unavailable."
        ) from exc

    return Response(
        content=data,
        media_type=document.content_type or "application/octet-stream",
        headers={
            # `attachment` matters: several accepted types would otherwise
            # render in the browser, and an HTML-ish file rendering on our
            # origin would be a stored-XSS vector.
            "Content-Disposition": f'attachment; filename="{document.file_name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
