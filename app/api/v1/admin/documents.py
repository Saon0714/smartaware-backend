"""Staff document management — spec Section 5.3.F."""

import uuid
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import (
    CallerClientScope,
    CurrentUser,
    DbSession,
    require_permission,
)
from app.core.permissions import Permission
from app.core.rate_limit import client_ip
from app.models.client import Client
from app.models.document import Document
from app.models.enums import DocumentDirection, DocumentType
from app.models.user import User
from app.schemas.document import DocumentCounts, DownloadOut, StaffDocumentOut
from app.services import document_service
from app.services.notification import NotificationEvent, dispatch, prepare
from app.services.storage import StorageError, get_storage

router = APIRouter(prefix="/admin", tags=["admin-documents"])

_can_view = Depends(require_permission(Permission.DOCUMENT_VIEW))
_can_upload = Depends(require_permission(Permission.DOCUMENT_UPLOAD_AS_STAFF))
#: Admin only.
_can_delete = Depends(require_permission(Permission.DOCUMENT_DELETE))


def _serialise(db: Session, document: Document, superseded: set) -> dict:
    client = db.get(Client, document.client_id)
    uploader = db.get(User, document.uploaded_by_id) if document.uploaded_by_id else None
    return {
        "id": document.id,
        "client_id": document.client_id,
        "client_ref": client.client_ref if client else "",
        "client_company_name": client.company_name if client else None,
        "direction": document.direction,
        "doc_type": document.doc_type,
        "file_name": document.file_name,
        "content_type": document.content_type,
        "size_bytes": document.size_bytes,
        "version": document.version,
        "supersedes_id": document.supersedes_id,
        "created_at": document.created_at,
        "uploaded_by_name": ((uploader.full_name or uploader.email) if uploader else None),
        "uploaded_by_email": uploader.email if uploader else None,
        "is_superseded": document.id in superseded,
        "is_archived": document.is_archived,
    }


def _load(db: Session, scope, document_id: uuid.UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None or not scope.allows(document.client_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return document


@router.get(
    "/documents",
    response_model=list[StaffDocumentOut],
    dependencies=[_can_view],
    name="list",
)
def list_documents(
    db: DbSession,
    scope: CallerClientScope,
    client_id: Annotated[uuid.UUID | None, Query()] = None,
    direction: Annotated[DocumentDirection | None, Query()] = None,
    doc_type: Annotated[DocumentType | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
) -> Any:
    stmt = select(Document).order_by(Document.created_at.desc())
    stmt = scope.apply(stmt, Document.client_id)

    if not include_archived:
        stmt = stmt.where(Document.is_archived.is_(False))
    if client_id is not None:
        stmt = stmt.where(Document.client_id == client_id)
    if direction is not None:
        stmt = stmt.where(Document.direction == direction)
    if doc_type is not None:
        stmt = stmt.where(Document.doc_type == doc_type)

    documents = list(db.execute(stmt).scalars())
    superseded = {d.supersedes_id for d in documents if d.supersedes_id is not None}
    return [_serialise(db, d, superseded) for d in documents]


@router.get(
    "/documents/counts",
    response_model=DocumentCounts,
    dependencies=[_can_view],
    name="counts",
)
def document_counts(db: DbSession, scope: CallerClientScope) -> Any:
    return document_service.counts_for(db, scope)


@router.post(
    "/documents",
    response_model=StaffDocumentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_can_upload],
    name="upload",
)
async def upload_for_client(
    user: CurrentUser,
    db: DbSession,
    scope: CallerClientScope,
    file: Annotated[UploadFile, File()],
    client_id: Annotated[uuid.UUID, Form()],
    doc_type: Annotated[DocumentType, Form()] = DocumentType.GENERAL,
) -> Any:
    """Share a document with a client (Section 5.3.F), and notify them."""
    if not scope.allows(client_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found.")

    data = await file.read()
    try:
        document = document_service.store(
            db,
            client_id=client_id,
            uploaded_by=user,
            direction=DocumentDirection.SMARTAWARE_TO_CLIENT,
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

    client = db.get(Client, client_id)
    message = prepare(
        db,
        NotificationEvent.SMARTAWARE_DOCUMENT_UPLOADED,
        {
            "client_name": (client.company_name if client else None) or "there",
            "file_name": document.file_name,
            "portal_url": f"{settings.FRONTEND_BASE_URL.rstrip('/')}/portal/documents",
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
    dependencies=[_can_view],
    name="download",
)
def request_download(
    document_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    scope: CallerClientScope,
) -> Any:
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
    dependencies=[_can_view],
    name="content",
    response_class=Response,
)
def download_content(
    document_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    scope: CallerClientScope,
) -> Response:
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
            "Content-Disposition": f'attachment; filename="{document.file_name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete(
    "/documents/{document_id}",
    response_model=StaffDocumentOut,
    dependencies=[_can_delete],
    name="archive",
)
def archive_document(document_id: uuid.UUID, db: DbSession, scope: CallerClientScope) -> Any:
    """Admin only, and an archive rather than a destruction.

    A client's tax records are exactly the thing not to delete on a single
    click, and Section 9 wants document actions traceable — which a removed row
    and a deleted object make impossible.
    """
    document = _load(db, scope, document_id)
    document.is_archived = True
    db.commit()
    db.refresh(document)
    return _serialise(db, document, set())
