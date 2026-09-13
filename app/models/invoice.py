"""Invoices and Wise payment reconciliation."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import InvoiceStatus, ReconciliationMethod
from app.models.user import _enum


class Invoice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Spec Sections 5.3.D and 12.

    Payment is a redirect to an Open Payment Link URL built from these fields.
    No Wise API call is involved in producing that URL — spec 12.1 rules it out.

    Reconciliation is the hard part, and it is manual for now (spec 12.4):
    Admin confirms the payment landed and marks the invoice Paid. The
    `reconciliation_method` and `external_payment_ref` columns exist so an
    automated matcher can be added later without a schema change.
    """

    __tablename__ = "invoices"

    client_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invoice_reference: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    service_description: Mapped[str] = mapped_column(String(512), nullable=False)

    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    status: Mapped[InvoiceStatus] = mapped_column(
        _enum(InvoiceStatus, "invoice_status"),
        default=InvoiceStatus.UNPAID,
        nullable=False,
        index=True,
    )
    issued_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Recorded when the client is redirected, purely for audit. The canonical
    # URL is always rebuilt by app.services.payment_link from live invoice data.
    wise_payment_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The Wise receipt the client uploads back into the portal (spec 5.3.D).
    receipt_document_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    reconciliation_method: Mapped[ReconciliationMethod | None] = mapped_column(
        _enum(ReconciliationMethod, "reconciliation_method"), nullable=True
    )
    reconciled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_payment_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
