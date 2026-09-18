"""Invoice schemas — spec Sections 5.3.D and 12."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import InvoiceStatus, ReconciliationMethod

#: What the portal and the staff list show, which is not quite `status`.
#:
#: `status` is the money: unpaid until somebody has looked at the Wise account.
#: But an invoice whose receipt has arrived is not in the same position as one
#: nobody has touched, and telling a client who has paid and uploaded their
#: receipt that their invoice is "unpaid" is both true and useless.
InvoiceState = Literal["unpaid", "overdue", "awaiting_confirmation", "paid", "cancelled"]


class InvoiceFileOut(BaseModel):
    """Enough to render a download link. The file itself is served by the
    documents endpoints, which already do the scoping and the audit."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file_name: str
    size_bytes: int | None = None
    uploaded_at: datetime | None = None


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    invoice_reference: str
    service_description: str
    amount: Decimal
    currency: str
    status: InvoiceStatus
    state: InvoiceState
    issued_at: date | None
    due_date: date | None
    created_at: datetime

    #: The invoice as shared, and the receipt as returned.
    document: InvoiceFileOut | None = None
    receipt: InvoiceFileOut | None = None

    #: Absent while no Open Payment Link is configured, which is how the portal
    #: knows to explain rather than offer a button that goes nowhere.
    pay_url: str | None = None


class StaffInvoiceOut(InvoiceOut):
    """Adds what only staff should see: who settled it and against what."""

    client_name: str | None = None
    notes: str | None = None
    reconciliation_method: ReconciliationMethod | None = None
    reconciled_at: datetime | None = None
    reconciled_by: str | None = None
    external_payment_ref: str | None = None


class InvoiceCreate(BaseModel):
    client_id: uuid.UUID
    service_description: str = Field(min_length=1, max_length=512)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    #: Left out to have one allocated: INV-<year>-<sequence>.
    invoice_reference: str | None = Field(default=None, max_length=64)
    issued_at: date | None = None
    due_date: date | None = None
    notes: str | None = None


class InvoiceUpdate(BaseModel):
    service_description: str | None = Field(default=None, min_length=1, max_length=512)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    issued_at: date | None = None
    due_date: date | None = None
    notes: str | None = None


class MarkPaidRequest(BaseModel):
    """Recorded against the person who decided it, because "the system says
    paid" and "someone checked the Wise account" are different claims."""

    external_payment_ref: str | None = Field(
        default=None,
        max_length=255,
        description="The Wise transaction reference, so the decision can be re-checked.",
    )
    note: str | None = None


class InvoiceCounts(BaseModel):
    unpaid: int = 0
    overdue: int = 0
    paid: int = 0
    cancelled: int = 0


class PayLinkOut(BaseModel):
    """The redirect target, handed over one invoice at a time.

    Built fresh from the invoice rather than read back from the row: an amount
    corrected after a first attempt must not still be payable at the old
    figure.
    """

    invoice_reference: str
    amount: Decimal
    currency: str
    pay_url: str
