"""A client's invoices, and paying them — spec Sections 5.3.D and 12.

The whole payment is a redirect. Wise cannot tell us the money arrived, so
this endpoint set is deliberately modest: show what is owed, hand over a URL,
take the receipt back, and leave the decision about whether an invoice is paid
to a person looking at the Wise account.

Everything is scoped to the caller's own client. The client_id is never taken
from the request — a client has exactly one, and it comes from their session.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.core.config import settings
from app.core.deps import CallerClientScope, CurrentUser, DbSession
from app.models.enums import DocumentDirection, DocumentType, InvoiceStatus
from app.models.invoice import Invoice
from app.schemas.invoice import InvoiceCounts, InvoiceOut, PayLinkOut
from app.services import document_service, invoice_service, payment_link
from app.services.notification import NotificationEvent, dispatch, prepare
from app.services.storage import StorageError

router = APIRouter(prefix="/portal", tags=["portal-invoices"])


def _my_client_id(scope) -> uuid.UUID:
    if len(scope.client_ids) != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a client account can use this.",
        )
    return next(iter(scope.client_ids))


def _load(db, scope, invoice_id: uuid.UUID) -> Invoice:
    invoice = invoice_service.get(db, scope, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")
    return invoice


@router.get("/invoices", response_model=list[InvoiceOut], summary="My invoices")
def my_invoices(db: DbSession, scope: CallerClientScope) -> Any:
    stmt = invoice_service.visible(scope).order_by(
        Invoice.issued_at.desc().nullslast(), Invoice.created_at.desc(), Invoice.id
    )
    return [invoice_service.serialise(db, invoice) for invoice in db.execute(stmt).scalars()]


@router.get("/invoices/counts", response_model=InvoiceCounts, summary="My invoice counts")
def my_invoice_counts(db: DbSession, scope: CallerClientScope) -> Any:
    return invoice_service.counts_for(db, scope)


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut, summary="One invoice")
def my_invoice(invoice_id: uuid.UUID, db: DbSession, scope: CallerClientScope) -> Any:
    return invoice_service.serialise(db, _load(db, scope, invoice_id))


@router.post("/invoices/{invoice_id}/pay", response_model=PayLinkOut, summary="Start a payment")
def start_payment(invoice_id: uuid.UUID, db: DbSession, scope: CallerClientScope) -> Any:
    """Hand back the Wise URL, and note that it was handed over.

    A POST rather than a GET because it writes: the URL a client was actually
    sent to is worth having when a payment later has to be matched by hand.
    It records an attempt and nothing more — opening Wise is not paying, so the
    invoice stays exactly as unpaid as it was.
    """
    invoice = _load(db, scope, invoice_id)

    if invoice.status is InvoiceStatus.PAID:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This invoice is already paid."
        )
    if invoice.status is InvoiceStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This invoice has been cancelled."
        )

    url = payment_link.for_invoice(db, invoice)
    if url is None:
        # Said plainly rather than as a failure the client could act on: they
        # cannot fix a link SmartAWARE has not supplied.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Online payment is not available yet. Please contact SmartAWARE "
                "and the team will arrange payment with you."
            ),
        )

    invoice_service.record_payment_redirect(db, invoice, url)
    db.commit()
    return {
        "invoice_reference": invoice.invoice_reference,
        "amount": invoice.amount,
        "currency": invoice.currency,
        "pay_url": url,
    }


@router.post(
    "/invoices/{invoice_id}/receipt",
    response_model=InvoiceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Send the payment receipt back",
)
async def upload_receipt(
    invoice_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    scope: CallerClientScope,
    file: Annotated[UploadFile, File()],
) -> Any:
    """The client's half of reconciliation.

    Nothing about this marks the invoice paid — it puts the proof in front of
    the people who can check it. Section 7 routes that to the administrator and
    the client's own manager rather than the whole team, because it is a
    request to do something rather than news.
    """
    invoice = _load(db, scope, invoice_id)
    _my_client_id(scope)

    if invoice.status is InvoiceStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This invoice has been cancelled."
        )

    data = await file.read()
    try:
        document = document_service.store(
            db,
            client_id=invoice.client_id,
            uploaded_by=user,
            direction=DocumentDirection.CLIENT_TO_SMARTAWARE,
            doc_type=DocumentType.INVOICE,
            filename=file.filename or f"{invoice.invoice_reference}-receipt",
            data=data,
            content_type=file.content_type,
        )
        invoice_service.attach_receipt(db, invoice, document)
    except (document_service.DocumentError, invoice_service.InvoiceError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    client = user.client
    message = prepare(
        db,
        NotificationEvent.CLIENT_INVOICE_UPLOADED,
        {
            "client_name": (client.company_name if client else None) or user.email,
            "file_name": document.file_name,
            "invoice_reference": invoice.invoice_reference,
            "admin_url": f"{settings.FRONTEND_BASE_URL.rstrip('/')}/admin/invoices",
        },
        client_id=invoice.client_id,
    )
    db.commit()
    dispatch(message)

    db.refresh(invoice)
    return invoice_service.serialise(db, invoice)
