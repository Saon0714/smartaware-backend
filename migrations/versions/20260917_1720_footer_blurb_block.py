"""footer blurb block

Revision ID: 8d31a6b4f207
Revises: 67b200d0c7ba
Create Date: 2026-09-17 17:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8d31a6b4f207"
down_revision: str | None = "67b200d0c7ba"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


KEY = "footer_blurb"
BODY = (
    "Professional tax, accounting and compliance advisory services for "
    "individuals and businesses in the United Kingdom, India, the UAE and Oman."
)


def upgrade() -> None:
    """Make the footer's standfirst editable.

    It was written into the frontend, so the one paragraph that appears on
    every page was the one paragraph SmartAWARE could not change. The seeder
    only inserts into an empty install, so existing databases need the row
    adding here — guarded, in case the seeder already ran against this one.
    """
    op.execute(
        sa.text(
            """
            INSERT INTO content_blocks (id, key, title, body, sort_order, is_published,
                                        created_at, updated_at)
            SELECT gen_random_uuid(), :key, 'Footer introduction', :body, 9, true,
                   now(), now()
            WHERE NOT EXISTS (SELECT 1 FROM content_blocks WHERE key = :key)
            """
        ).bindparams(key=KEY, body=BODY)
    )


def downgrade() -> None:
    """Only removes the row if it still holds the text this added."""
    op.execute(
        sa.text("DELETE FROM content_blocks WHERE key = :key AND body = :body").bindparams(
            key=KEY, body=BODY
        )
    )
