"""apply reseeded copy to existing rows

Revision ID: 1ec8e76bf978
Revises: c0cf86ec6a04
Create Date: 2026-09-15 11:46:08.248750
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '1ec8e76bf978'
down_revision: str | None = 'c0cf86ec6a04'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


SHORT_NAMES = {"uk": "UK", "india": "India", "uae": "UAE", "oman": "Oman"}

OLD_HERO = "Professional UK Tax & Compliance Advisory"
NEW_HERO = "Professional {region} Tax & Compliance Advisory"

STRENGTH_ICONS = {
    "Experience Since 2016": "award",
    "Strong UK Focus": "map-pin",
    "International Reach": "globe",
    "Comprehensive Accounting & Tax Services": "layers",
    "Personalised Professional Service": "user-check",
    "Secure Data Protection": "shield",
    "Professional Communication": "message",
}


def upgrade() -> None:
    """Bring rows seeded by an earlier build up to the current seed data.

    The seeder only ever inserts what is missing, which is deliberate — it must
    never overwrite something an editor has changed. The consequence is that a
    database created before these values changed keeps the old ones for ever,
    and the only sign is the feature quietly not working: a heading that names
    the same market whichever country is chosen, strengths numbered 01, 02, 03
    because no icon is set.

    So the updates live here, where they run for everyone exactly once, and each
    is guarded to touch only rows that still hold the previous seeded value.
    Anything edited in the Admin Portal is left exactly as it is.

    Rows that are missing entirely are still the seeder's job: run
    `python scripts/seed.py` to pick up new content such as the placeholder
    reviews.
    """
    connection = op.get_bind()

    # The short form used inside a sentence. Only where none has been set.
    for slug, short in SHORT_NAMES.items():
        connection.execute(
            sa.text(
                "UPDATE regions SET short_name = :short "
                "WHERE slug = :slug AND short_name IS NULL"
            ),
            {"short": short, "slug": slug},
        )

    # The homepage heading names the chosen market through a {region} token.
    connection.execute(
        sa.text(
            "UPDATE content_blocks SET title = :new "
            "WHERE key = 'home_hero' AND title = :old"
        ),
        {"new": NEW_HERO, "old": OLD_HERO},
    )

    # Key strengths were shipped without icons and fell back to their position.
    for title, icon in STRENGTH_ICONS.items():
        connection.execute(
            sa.text(
                "UPDATE key_strengths SET icon_key = :icon "
                "WHERE title = :title AND icon_key IS NULL"
            ),
            {"icon": icon, "title": title},
        )


def downgrade() -> None:
    """Put back what this set, and only where it is still what this set."""
    connection = op.get_bind()

    connection.execute(
        sa.text(
            "UPDATE content_blocks SET title = :old "
            "WHERE key = 'home_hero' AND title = :new"
        ),
        {"new": NEW_HERO, "old": OLD_HERO},
    )
    for title, icon in STRENGTH_ICONS.items():
        connection.execute(
            sa.text(
                "UPDATE key_strengths SET icon_key = NULL "
                "WHERE title = :title AND icon_key = :icon"
            ),
            {"icon": icon, "title": title},
        )
    for slug, short in SHORT_NAMES.items():
        connection.execute(
            sa.text(
                "UPDATE regions SET short_name = NULL "
                "WHERE slug = :slug AND short_name = :short"
            ),
            {"short": short, "slug": slug},
        )
