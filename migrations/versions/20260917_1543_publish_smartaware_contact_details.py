"""publish smartaware contact details

Revision ID: 67b200d0c7ba
Revises: 1ec8e76bf978
Create Date: 2026-09-17 15:43:26.276881
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '67b200d0c7ba'
down_revision: str | None = '1ec8e76bf978'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


PLACEHOLDER = "[AWAITING SMARTAWARE]"

#: label -> the value SmartAWARE supplied. Only rows still holding the
#: placeholder are touched.
SUPPLIED = {
    "Registered Office": (
        "Office 19228\n182-184 High St North\nEast Ham\nLondon\nE6 2JA"
    ),
    "General Enquiries": "info@smartaware.co.uk",
    "Telephone": "+44 20 3051 6990",
    "WhatsApp": "+44 20 3051 6990",
    "Working Hours": (
        "8am to 5pm BST, Monday to Friday\nClosed weekends and UK bank holidays"
    ),
}


def upgrade() -> None:
    """Fill in the contact details that shipped as unpublished placeholders.

    These five rows exist on every install, seeded as `[AWAITING SMARTAWARE]`
    and withheld from the website so it could not show an invented address as
    though it were real. SmartAWARE has now supplied them.

    The seeder cannot do this: it only inserts what is missing, so on an
    existing database these rows would keep the placeholder for ever. Rows that
    do not exist yet — the map link and the per-market new-business numbers —
    are still its job.

    Guarded on the placeholder value, so anything already edited in the Admin
    Portal is left exactly as it is, and publishing only happens for rows this
    migration actually filled in.
    """
    connection = op.get_bind()
    for label, value in SUPPLIED.items():
        connection.execute(
            sa.text(
                "UPDATE contact_details SET value = :value, is_published = true "
                "WHERE label = :label AND value = :placeholder"
            ),
            {"value": value, "label": label, "placeholder": PLACEHOLDER},
        )


def downgrade() -> None:
    """Back to withheld placeholders, and only where the value is untouched."""
    connection = op.get_bind()
    for label, value in SUPPLIED.items():
        connection.execute(
            sa.text(
                "UPDATE contact_details SET value = :placeholder, is_published = false "
                "WHERE label = :label AND value = :value"
            ),
            {"value": value, "label": label, "placeholder": PLACEHOLDER},
        )
