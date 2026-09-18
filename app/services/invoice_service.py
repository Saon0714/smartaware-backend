"""Invoices and their reconciliation — spec Sections 5.3.D and 12.

Payment is a redirect, so nothing here ever learns from Wise that money
arrived. That is the shape of the integration rather than an omission: Wise's
public API cannot create the payment link, and the guide's recommendation is
that reconciliation starts manual. So an invoice is only ever marked paid by a
person who has looked at the Wise account and said so, and the columns that
record who and when exist because "it says paid" is not the same as "we know
who decided that".
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.document import Document
from app.models.enums import DocumentDirection, DocumentType, InvoiceStatus, ReconciliationMethod
from app.models.invoice import Invoice
from app.models.user import User
from app.services import payment_link

#: Currencies an invoice may be raised in — the markets SmartAWARE serves, plus
#: the euro, which UK practices bill in often enough to matter. Checked because
#: the code is passed to Wise, where an unknown one is a dead end rather than a
#: validation error the client can act on.
CURRENCIES = ("GBP", "EUR", "USD", "INR", "AED", "OMR")

MAX_REFERENCE_ATTEMPTS = 50


class InvoiceError(Exception):
    """Rejected. The message is safe to show the caller."""


def visible(scope, stmt: Select | None = None) -> Select:
    """Every invoice query starts here, so client isolation is a property of
    the query rather than something each endpoint remembers."""
    stmt = select(Invoice) if stmt is None else stmt
    return scope.apply(stmt, Invoice.client_id)


def get(db: Session, scope, invoice_id: uuid.UUID) -> Invoice | None:
    return db.execute(visible(scope).where(Invoice.id == invoice_id)).scalar_one_or_none()


def next_reference(db: Session, when: date | None = None) -> str:
    """A readable reference in the year it was raised.

    It is what the client types nothing of and Wise carries everything of: it
    travels in the payment description and is the only thread back to this
    invoice once the money is inside Wise. Sequential within the year so two
    raised on the same day are still told apart by eye.
    """
    year = (when or date.today()).year
    prefix = f"INV-{year}-"
    used = {
        reference
        for reference in db.execute(
            select(Invoice.invoice_reference).where(Invoice.invoice_reference.like(f"{prefix}%"))
        ).scalars()
    }
    for index in range(1, len(used) + MAX_REFERENCE_ATTEMPTS + 1):
        candidate = f"{prefix}{index:04d}"
        if candidate not in used:
            return candidate
    raise InvoiceError("Could not allocate an invoice reference.")


def create(
    db: Session,
    *,
    client_id: uuid.UUID,
    service_description: str,
    amount: Decimal,
    currency: str,
    invoice_reference: str | None = None,
    issued_at: date | None = None,
    due_date: date | None = None,
    notes: str | None = None,
) -> Invoice:
    currency = (currency or "").strip().upper()
    if currency not in CURRENCIES:
        raise InvoiceError(f"Currency must be one of: {', '.join(CURRENCIES)}.")
    if amount is None or Decimal(amount) <= 0:
        raise InvoiceError("The amount must be more than zero.")

    reference = (invoice_reference or "").strip() or next_reference(db, issued_at)
    if db.execute(
        select(Invoice.id).where(Invoice.invoice_reference == reference)
    ).scalar_one_or_none():
        raise InvoiceError(f"Invoice {reference} already exists.")

    invoice = Invoice(
        client_id=client_id,
        invoice_reference=reference,
        service_description=service_description.strip(),
        amount=Decimal(amount),
        currency=currency,
        status=InvoiceStatus.UNPAID,
        issued_at=issued_at or date.today(),
        due_date=due_date,
        notes=(notes or None),
    )
    db.add(invoice)
    db.flush()
    return invoice


def update(db: Session, invoice: Invoice, changes: dict[str, Any]) -> Invoice:
    """Amend an invoice that has not been settled.

    A paid invoice is a record of a transaction rather than a draft, so it is
    left alone — correcting one after the money moved means raising a credit
    note, which is an accounting decision and not an edit.
    """
    if invoice.status is InvoiceStatus.PAID:
        raise InvoiceError("A paid invoice cannot be edited.")

    if "currency" in changes:
        currency = (changes["currency"] or "").strip().upper()
        if currency not in CURRENCIES:
            raise InvoiceError(f"Currency must be one of: {', '.join(CURRENCIES)}.")
        changes["currency"] = currency
    if "amount" in changes and (changes["amount"] is None or Decimal(changes["amount"]) <= 0):
        raise InvoiceError("The amount must be more than zero.")

    for field, value in changes.items():
        setattr(invoice, field, value)
    db.flush()
    return invoice


def mark_paid(
    db: Session,
    invoice: Invoice,
    *,
    by: User,
    external_payment_ref: str | None = None,
    note: str | None = None,
) -> Invoice:
    """Record that the money arrived, and who checked.

    Manual by design (spec 12.4): the redirect tells us a client opened Wise,
    never that they paid. Somebody reads the Wise account and says so.
    """
    if invoice.status is InvoiceStatus.PAID:
        raise InvoiceError("This invoice is already marked as paid.")
    if invoice.status is InvoiceStatus.CANCELLED:
        raise InvoiceError("A cancelled invoice cannot be marked as paid.")

    invoice.status = InvoiceStatus.PAID
    invoice.reconciliation_method = ReconciliationMethod.MANUAL
    invoice.reconciled_by_id = by.id
    invoice.reconciled_at = datetime.now(UTC)
    if external_payment_ref:
        invoice.external_payment_ref = external_payment_ref.strip()[:255]
    if note:
        invoice.notes = f"{invoice.notes}\n{note}".strip() if invoice.notes else note
    db.flush()
    return invoice


def cancel(db: Session, invoice: Invoice) -> Invoice:
    if invoice.status is InvoiceStatus.PAID:
        raise InvoiceError("A paid invoice cannot be cancelled.")
    invoice.status = InvoiceStatus.CANCELLED
    db.flush()
    return invoice


def record_payment_redirect(db: Session, invoice: Invoice, url: str) -> Invoice:
    """Note that a client was sent to Wise.

    Evidence that the journey started, and nothing more. It is deliberately not
    a status change: a person who opens Wise and closes the tab has not paid,
    and an invoice that looked settled on the strength of a click would be
    worse than one that looked unpaid.
    """
    invoice.wise_payment_url = url
    db.flush()
    return invoice


def attach_receipt(db: Session, invoice: Invoice, document: Document) -> Invoice:
    if document.client_id != invoice.client_id:
        raise InvoiceError("That document belongs to another client.")
    if document.direction is not DocumentDirection.CLIENT_TO_SMARTAWARE:
        raise InvoiceError("A receipt is something the client uploads.")
    invoice.receipt_document_id = document.id
    db.flush()
    return invoice


def attach_issued_document(db: Session, invoice: Invoice, document: Document) -> Invoice:
    if document.client_id != invoice.client_id:
        raise InvoiceError("That document belongs to another client.")
    if document.doc_type is not DocumentType.INVOICE:
        raise InvoiceError("The invoice file must be filed as an invoice.")
    invoice.document_id = document.id
    db.flush()
    return invoice


def counts_for(db: Session, scope) -> dict[str, int]:
    """Totals for the portal and the staff overview, scoped like everything else."""
    rows = db.execute(
        visible(scope, select(Invoice.status, func.count()).select_from(Invoice)).group_by(
            Invoice.status
        )
    ).all()
    by_status = {status: count for status, count in rows}
    unpaid = by_status.get(InvoiceStatus.UNPAID, 0)

    overdue = db.execute(
        visible(scope, select(func.count()).select_from(Invoice)).where(
            Invoice.status == InvoiceStatus.UNPAID,
            Invoice.due_date.is_not(None),
            Invoice.due_date < date.today(),
        )
    ).scalar_one()

    return {
        "unpaid": unpaid,
        "paid": by_status.get(InvoiceStatus.PAID, 0),
        "cancelled": by_status.get(InvoiceStatus.CANCELLED, 0),
        "overdue": overdue,
    }


def _file(db: Session, document_id: uuid.UUID | None) -> dict | None:
    if document_id is None:
        return None
    document = db.get(Document, document_id)
    if document is None or document.is_archived:
        return None
    return {
        "id": document.id,
        "file_name": document.file_name,
        "size_bytes": document.size_bytes,
        "uploaded_at": document.created_at,
    }


def state_of(invoice: Invoice, today: date | None = None) -> str:
    """What to call this invoice on screen.

    Derived rather than stored, so it cannot drift from `status`. The extra
    state that matters is the gap the redirect leaves: a client who has paid
    and sent their receipt is waiting on SmartAWARE, not the other way round,
    and "unpaid" would put the fault in the wrong place.
    """
    if invoice.status is InvoiceStatus.PAID:
        return "paid"
    if invoice.status is InvoiceStatus.CANCELLED:
        return "cancelled"
    if invoice.receipt_document_id is not None:
        return "awaiting_confirmation"
    if invoice.due_date and invoice.due_date < (today or date.today()):
        return "overdue"
    return "unpaid"


def serialise(db: Session, invoice: Invoice, *, for_staff: bool = False) -> dict:
    """One shape for both portals, with the staff-only fields added on top.

    Written once because the two views must agree about what an invoice says.
    A client reading "£500, unpaid" and an administrator reading something else
    about the same row is the bug this prevents.
    """
    payable = invoice.status is InvoiceStatus.UNPAID
    data = {
        "id": invoice.id,
        "client_id": invoice.client_id,
        "invoice_reference": invoice.invoice_reference,
        "service_description": invoice.service_description,
        "amount": invoice.amount,
        "currency": invoice.currency,
        "status": invoice.status,
        "state": state_of(invoice),
        "issued_at": invoice.issued_at,
        "due_date": invoice.due_date,
        "created_at": invoice.created_at,
        "document": _file(db, invoice.document_id),
        "receipt": _file(db, invoice.receipt_document_id),
        "pay_url": payment_link.for_invoice(db, invoice) if payable else None,
    }
    if not for_staff:
        return data

    reconciler = db.get(User, invoice.reconciled_by_id) if invoice.reconciled_by_id else None
    client = db.get(Client, invoice.client_id)
    data.update(
        {
            "client_name": client.company_name if client else None,
            "notes": invoice.notes,
            "reconciliation_method": invoice.reconciliation_method,
            "reconciled_at": invoice.reconciled_at,
            "reconciled_by": (reconciler.full_name or reconciler.email) if reconciler else None,
            "external_payment_ref": invoice.external_payment_ref,
        }
    )
    return data
