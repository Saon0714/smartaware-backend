"""invoice issued document

Revision ID: 1d94f8e0980c
Revises: 2f5b90c41d63
Create Date: 2026-09-18 14:03:40.012085
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1d94f8e0980c"
down_revision: str | None = "2f5b90c41d63"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

CONSTRAINT = "fk_invoices_document_id_documents"


def upgrade() -> None:
    """Link an invoice to the file it was sent as.

    `receipt_document_id` already recorded the client's side of the exchange.
    This is the other half: the invoice SmartAWARE shared, so the portal can
    put the figures and the file on one card instead of asking a client to
    match a PDF in their documents against an amount somewhere else.

    Nullable, because the figures are what gets paid — an amount and a
    reference are enough to raise and settle an invoice before anyone attaches
    a PDF of it.
    """
    op.add_column("invoices", sa.Column("document_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        CONSTRAINT, "invoices", "documents", ["document_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "invoices", type_="foreignkey")
    op.drop_column("invoices", "document_id")
