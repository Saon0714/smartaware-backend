"""faq updated_at trigger

Revision ID: 50036d4393f5
Revises: b9abb09a801a
Create Date: 2026-09-13 13:28:58.354007
"""

from collections.abc import Sequence

from alembic import op

revision: str = "50036d4393f5"
down_revision: str | None = "b9abb09a801a"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Maintain faq_entries.updated_at in the database, not only in the ORM.

    The incremental re-index (spec 4.4) decides what to embed by comparing
    updated_at against indexed_at. SQLAlchemy's `onupdate` only fires for writes
    that go through the ORM, so a bulk load or a hand-written UPDATE — both
    plausible for FAQ content — would leave updated_at untouched and the entry
    would never be re-embedded. The symptom is silent and confusing: the answer
    changes but the chatbot keeps giving the old one.

    Only faq_entries gets this, because only here does correctness depend on it.
    """
    op.execute(
        """
        CREATE OR REPLACE FUNCTION faq_entries_touch_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            -- Left alone when the row is only being marked as indexed,
            -- otherwise the indexer would make its own work look stale again.
            IF NEW.indexed_at IS DISTINCT FROM OLD.indexed_at
               AND NEW.question IS NOT DISTINCT FROM OLD.question
               AND NEW.answer IS NOT DISTINCT FROM OLD.answer
               AND NEW.is_published IS NOT DISTINCT FROM OLD.is_published
               AND NEW.is_deleted IS NOT DISTINCT FROM OLD.is_deleted THEN
                RETURN NEW;
            END IF;
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER faq_entries_set_updated_at
        BEFORE UPDATE ON faq_entries
        FOR EACH ROW EXECUTE FUNCTION faq_entries_touch_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS faq_entries_set_updated_at ON faq_entries")
    op.execute("DROP FUNCTION IF EXISTS faq_entries_touch_updated_at()")
