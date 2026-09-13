"""client services

Revision ID: 681e93ee60ac
Revises: 50036d4393f5
Create Date: 2026-09-13 20:34:15.263513
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "681e93ee60ac"
down_revision: str | None = "50036d4393f5"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Record which services a client is engaged for.

    A join table rather than a column on `clients`: taking several services at
    once is the normal case, and the admin client list has to filter on one of
    them without the client appearing once per service.

    It points at the same `service_categories` the website and tasks use, so
    what SmartAWARE advertises, what a client buys and what a manager is working
    on all refer to one taxonomy.
    """
    op.create_table(
        "client_services",
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["category_id"], ["service_categories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("client_id", "category_id"),
    )
    # The primary key indexes client-first lookups. The admin list filters the
    # other way round -- "who takes payroll?" -- which that index cannot serve.
    op.create_index("ix_client_services_category_id", "client_services", ["category_id"])


def downgrade() -> None:
    op.drop_index("ix_client_services_category_id", table_name="client_services")
    op.drop_table("client_services")
