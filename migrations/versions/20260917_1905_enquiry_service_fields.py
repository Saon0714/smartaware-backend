"""enquiry service fields

Revision ID: 4a7c02e9b118
Revises: 8d31a6b4f207
Create Date: 2026-09-17 19:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4a7c02e9b118"
down_revision: str | None = "8d31a6b4f207"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Let an enquiry name several services, and the specific services under them.

    Three changes to the seeded enquiry form, each guarded so an install whose
    form SmartAWARE has already edited is left alone:

      * "Service Required" takes more than one answer, and is renamed to match.
      * A "Specific Services" field replaces the free-text box the service
        pages used to write a sentence into. Its options are narrowed in the
        browser from the live catalogue, so nothing is stored against it here.
      * "Nature of Requirement" is retired. It asked for the same thing twice
        once the specific services are picked from a list, and it is the field
        the sentence was being written into. Deactivated rather than deleted:
        enquiries already sent hold answers under that key, and the row is what
        gives those answers a label.
    """
    connection = op.get_bind()
    form_id = connection.execute(
        sa.text("SELECT id FROM form_definitions WHERE key = 'enquiry'")
    ).scalar()
    if form_id is None:
        return

    connection.execute(
        sa.text(
            """
            UPDATE form_fields
               SET field_type = 'multiselect', label = 'Services Required',
                   help_text = 'Choose as many as apply.'
             WHERE form_id = :form AND key = 'service_required'
               AND field_type = 'select' AND label = 'Service Required'
            """
        ).bindparams(form=form_id)
    )

    connection.execute(
        sa.text(
            """
            INSERT INTO form_fields (id, form_id, key, label, field_type, is_required,
                                     options, sort_order, is_active, help_text,
                                     created_at, updated_at)
            SELECT gen_random_uuid(), :form, 'sub_services', 'Specific Services',
                   'multiselect', false, '[]'::jsonb, 7, true,
                   'Follows from the country and services chosen above.', now(), now()
             WHERE NOT EXISTS (
                     SELECT 1 FROM form_fields WHERE form_id = :form AND key = 'sub_services')
            """
        ).bindparams(form=form_id)
    )

    connection.execute(
        sa.text(
            """
            UPDATE form_fields SET is_active = false
             WHERE form_id = :form AND key = 'nature_of_requirement'
               AND label = 'Nature of Requirement'
            """
        ).bindparams(form=form_id)
    )

    connection.execute(
        sa.text(
            """
            UPDATE form_fields
               SET help_text = 'Anything else you would like us to know. Optional.'
             WHERE form_id = :form AND key = 'additional_information'
               AND help_text IS NULL
            """
        ).bindparams(form=form_id)
    )


def downgrade() -> None:
    connection = op.get_bind()
    form_id = connection.execute(
        sa.text("SELECT id FROM form_definitions WHERE key = 'enquiry'")
    ).scalar()
    if form_id is None:
        return
    connection.execute(
        sa.text(
            "DELETE FROM form_fields WHERE form_id = :form AND key = 'sub_services'"
        ).bindparams(form=form_id)
    )
    connection.execute(
        sa.text(
            """
            UPDATE form_fields SET is_active = true
             WHERE form_id = :form AND key = 'nature_of_requirement'
            """
        ).bindparams(form=form_id)
    )
    connection.execute(
        sa.text(
            """
            UPDATE form_fields
               SET field_type = 'select', label = 'Service Required',
                   help_text = 'Options are sourced from the published service categories.'
             WHERE form_id = :form AND key = 'service_required'
            """
        ).bindparams(form=form_id)
    )
