"""region short name and trustpilot testimonials

Revision ID: c0cf86ec6a04
Revises: 5f85b6dbb0cf
Create Date: 2026-09-14 12:53:22.674143
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c0cf86ec6a04"
down_revision: str | None = "5f85b6dbb0cf"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """A market's short name, and the fields a Trustpilot import needs.

    `regions.short_name` is the form used inside a sentence — "Professional UK
    Tax & Compliance Advisory". The formal `name` reads badly there
    ("Professional United Kingdom Tax..."), so it is its own field rather than
    something derived, and nullable so it falls back to `name`.

    On testimonials, `external_id` is the review's ID at its source and is
    unique, so a sync upserts instead of duplicating on every run. `source`
    separates imported reviews from ones SmartAWARE typed itself, so an import
    cannot quietly discard the latter. It carries a server default because the
    column is NOT NULL and this table may already have rows — without one the
    migration fails on any install that has testimonials.
    """
    op.add_column("regions", sa.Column("short_name", sa.String(length=64), nullable=True))

    op.add_column(
        "testimonials",
        sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
    )
    op.add_column("testimonials", sa.Column("external_id", sa.String(length=128), nullable=True))
    op.add_column("testimonials", sa.Column("source_url", sa.String(length=512), nullable=True))
    op.add_column("testimonials", sa.Column("reviewed_at", sa.Date(), nullable=True))
    op.create_index(
        "ix_testimonials_external_id", "testimonials", ["external_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_testimonials_external_id", table_name="testimonials")
    op.drop_column("testimonials", "reviewed_at")
    op.drop_column("testimonials", "source_url")
    op.drop_column("testimonials", "external_id")
    op.drop_column("testimonials", "source")
    op.drop_column("regions", "short_name")
