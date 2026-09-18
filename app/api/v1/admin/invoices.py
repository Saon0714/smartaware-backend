"""Staff invoice management — spec Sections 5.3.D and 12.

Raising an invoice and settling one are separate permissions on purpose.
Section 12.4 makes reconciliation a judgement about money that has or has not
arrived in the Wise account, so `invoice:reconcile` is Admin-only while a
Manager can read the invoices of the clients they hold.
"""

import uuid
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)

from app.core.config import settings
from app.core.deps import CallerClientScope, CurrentUser, DbSession, require_permission
from app.core.permissions import Permission
from app.core.rate_limit import client_ip
from app.models.client import Client
from app.models.enums import DocumentDirection, DocumentType, InvoiceStatus
from app.models.invoice import Invoice
from app.schemas.invoice import (
    InvoiceCounts,
    InvoiceCreate,
    InvoiceUpdate,
    MarkPaidRequest,
    StaffInvoiceOut,
)
from app.services import audit_service, document_service, invoice_service
from app.services.notification import NotificationEvent, dispatch, prepare
from app.services.storage import StorageError

router = APIRouter(prefix="/admin", tags=["admin-invoices"])

_can_view = Depends(require_permission(Permission.INVOICE_VIEW))
_can_manage = Depends(require_permission(Permission.INVOICE_MANAGE))
_can_reconcile = Depends(require_permission(Permission.INVOICE_RECONCILE))


def _load(db, scope, invoice_id: uuid.UUID) -> Invoice:
    invoice = invoice_service.get(db, scope, invoice_id)
    if invoice is None:
        # 404 rather than 403 for a client outside this caller's scope: telling
        # them the invoice exists is itself a disclosure.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")
    return invoice


@router.get(
    "/invoices",
    response_model=list[StaffInvoiceOut],
    dependencies=[_can_view],
    name="list",
)
def list_invoices(
    db: DbSession,
    scope: CallerClientScope,
    client_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[InvoiceStatus | None, Query(alias="status")] = None,
) -> Any:
    stmt = invoice_service.visible(scope).order_by(
        Invoice.issued_at.desc().nullslast(), Invoice.created_at.desc(), Invoice.id
    )
    if client_id is not None:
        if not scope.allows(client_id):
            return []
        stmt = stmt.where(Invoice.client_id == client_id)
    if status_filter is not None:
        stmt = stmt.where(Invoice.status == status_filter)

    return [
        invoice_service.serialise(db, invoice, for_staff=True)
        for invoice in db.execute(stmt).scalars()
    ]


@router.get(
    "/invoices/counts", response_model=InvoiceCounts, dependencies=[_can_view], name="counts"
)
def invoice_counts(db: DbSession, scope: CallerClientScope) -> Any:
    return invoice_service.counts_for(db, scope)


@router.post(
    "/invoices",
    response_model=StaffInvoiceOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_can_manage],
    name="create",
)
def create_invoice(payload: InvoiceCreate, db: DbSession, scope: CallerClientScope) -> Any:
    if not scope.allows(payload.client_id) or db.get(Client, payload.client_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found.")
    try:
        invoice = invoice_service.create(db, **payload.model_dump(exclude_unset=False))
    except invoice_service.InvoiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    db.commit()
    db.refresh(invoice)
    return invoice_service.serialise(db, invoice, for_staff=True)


@router.get(
    "/invoices/{invoice_id}",
    response_model=StaffInvoiceOut,
    dependencies=[_can_view],
    name="get",
)
def get_invoice(invoice_id: uuid.UUID, db: DbSession, scope: CallerClientScope) -> Any:
    return invoice_service.serialise(db, _load(db, scope, invoice_id), for_staff=True)


@router.patch(
    "/invoices/{invoice_id}",
    response_model=StaffInvoiceOut,
    dependencies=[_can_manage],
    name="update",
)
def update_invoice(
    invoice_id: uuid.UUID, payload: InvoiceUpdate, db: DbSession, scope: CallerClientScope
) -> Any:
    invoice = _load(db, scope, invoice_id)
    try:
        invoice_service.update(db, invoice, payload.model_dump(exclude_unset=True))
    except invoice_service.InvoiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    db.commit()
    db.refresh(invoice)
    return invoice_service.serialise(db, invoice, for_staff=True)


@router.post(
    "/invoices/{invoice_id}/document",
    response_model=StaffInvoiceOut,
    dependencies=[_can_manage],
    name="attach_document",
)
async def attach_invoice_document(
    invoice_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    scope: CallerClientScope,
    file: Annotated[UploadFile, File()],
) -> Any:
    """Share the invoice itself with the client, and tell them it is there.

    Filed as an ordinary document so it appears in their Documents as well —
    the invoice screen is a better place to find it, not the only one.
    """
    invoice = _load(db, scope, invoice_id)
    data = await file.read()
    try:
        document = document_service.store(
            db,
            client_id=invoice.client_id,
            uploaded_by=user,
            direction=DocumentDirection.SMARTAWARE_TO_CLIENT,
            doc_type=DocumentType.INVOICE,
            filename=file.filename or f"{invoice.invoice_reference}.pdf",
            data=data,
            content_type=file.content_type,
        )
        invoice_service.attach_issued_document(db, invoice, document)
    except document_service.DocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except invoice_service.InvoiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    client = db.get(Client, invoice.client_id)
    message = prepare(
        db,
        NotificationEvent.SMARTAWARE_DOCUMENT_UPLOADED,
        {
            "client_name": (client.company_name if client else None) or "there",
            "file_name": document.file_name,
            "portal_url": f"{settings.FRONTEND_BASE_URL.rstrip('/')}/portal/invoices",
        },
        client_id=invoice.client_id,
    )
    db.commit()
    dispatch(message)

    db.refresh(invoice)
    return invoice_service.serialise(db, invoice, for_staff=True)


@router.post(
    "/invoices/{invoice_id}/mark-paid",
    response_model=StaffInvoiceOut,
    dependencies=[_can_reconcile],
    name="mark_paid",
)
def mark_paid(
    invoice_id: uuid.UUID,
    payload: MarkPaidRequest,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    scope: CallerClientScope,
) -> Any:
    """Confirm the money arrived.

    Audited because this is the one action in the payment flow that no system
    verified: Wise told us nothing, the client's receipt is a claim, and what
    makes the invoice paid is a person saying they checked.
    """
    invoice = _load(db, scope, invoice_id)
    try:
        invoice_service.mark_paid(
            db,
            invoice,
            by=user,
            external_payment_ref=payload.external_payment_ref,
            note=payload.note,
        )
    except invoice_service.InvoiceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    audit_service.record(
        db,
        actor=user,
        action=audit_service.AuditAction.INVOICE_RECONCILED,
        entity_type="invoice",
        entity_id=invoice.id,
        new_value={
            "invoice_reference": invoice.invoice_reference,
            "amount": str(invoice.amount),
            "currency": invoice.currency,
            "external_payment_ref": invoice.external_payment_ref,
        },
        reason=payload.note,
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(invoice)
    return invoice_service.serialise(db, invoice, for_staff=True)


@router.post(
    "/invoices/{invoice_id}/cancel",
    response_model=StaffInvoiceOut,
    dependencies=[_can_manage],
    name="cancel",
)
def cancel_invoice(invoice_id: uuid.UUID, db: DbSession, scope: CallerClientScope) -> Any:
    invoice = _load(db, scope, invoice_id)
    try:
        invoice_service.cancel(db, invoice)
    except invoice_service.InvoiceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.commit()
    db.refresh(invoice)
    return invoice_service.serialise(db, invoice, for_staff=True)
