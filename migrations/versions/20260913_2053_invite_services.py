"""invite services

Revision ID: 5f85b6dbb0cf
Revises: 681e93ee60ac
Create Date: 2026-09-13 20:53:41.122039
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5f85b6dbb0cf"
down_revision: str | None = "681e93ee60ac"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """The services an invited client is being signed up for.

    A client does not choose what they are engaged for — the Admin decides when
    issuing the invitation, and redemption copies the choice onto the new client
    record. Holding it on the invite is what makes that true: nothing the person
    accepting the invitation sends can influence it.

    No index beyond the primary key. This is only ever read one invite at a
    time, on redemption and when listing invitations.
    """
    op.create_table(
        "invite_services",
        sa.Column("invite_id", sa.UUID(), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["service_categories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invite_id"], ["invites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("invite_id", "category_id"),
    )


def downgrade() -> None:
    op.drop_table("invite_services")
