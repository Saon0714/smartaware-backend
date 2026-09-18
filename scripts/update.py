"""Bring a database up to date with the code that was just pulled.

    uv run python scripts/update.py            # native
    docker compose exec api uv run python scripts/update.py   # Docker

Two things drift after a `git pull`, and they drift differently.

The *shape* of the database is Alembic's: every structural change ships as a
migration, and applying them in order is the only way a database that has been
sitting behind catches up. Skipping that is the usual cause of a page that
renders its heading and then an error, because the ORM selected a column the
table does not have.

The *contents* are split. New reference rows come from the seeder, which only
ever inserts — it will not overwrite a row somebody has edited, which is the
whole reason it is safe to re-run. Rows that already exist and need changing
cannot come from the seeder for exactly that reason, so they travel as
migrations too.

So: migrate, then seed, in that order, because a migration can add the table
the seeder is about to write to. This runs both and says what happened.

Idempotent. Running it on an up-to-date database applies nothing, inserts
nothing, and says so.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402

from app.db.session import SessionLocal, engine  # noqa: E402
from app.seeds.run import seed_all  # noqa: E402


def say(message: str = "") -> None:
    """Flushed, because Alembic logs to stderr as it works. Without this the
    script's own narration arrives after the migration output it introduces,
    which reads as though nothing was said before things started happening."""
    print(message, flush=True)


def _alembic_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


def _current_revision() -> str | None:
    """None when the database has never been migrated, which is a fresh install
    rather than an error."""
    with engine.connect() as connection:
        if not inspect(connection).has_table("alembic_version"):
            return None
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _pending(config: Config, current: str | None) -> list[str]:
    """The migrations between where this database is and where the code expects
    it to be, oldest first."""
    scripts = ScriptDirectory.from_config(config)
    revisions = list(scripts.walk_revisions("base", "heads"))
    revisions.reverse()

    if current is None:
        return [f"{r.revision}  {r.doc}" for r in revisions]

    seen = False
    pending = []
    for revision in revisions:
        if seen:
            pending.append(f"{revision.revision}  {revision.doc}")
        if revision.revision == current:
            seen = True
    return pending


def _summary(db) -> list[tuple[str, int]]:
    """A few counts, so "it worked" is something you can see rather than
    something you have to take on trust."""
    from sqlalchemy import func, select

    from app.models.content import ContentBlock
    from app.models.faq import FaqEntry
    from app.models.form_schema import FormField
    from app.models.service import Region, ServiceCategory
    from app.models.setting import Setting
    from app.models.user import User

    def count(model) -> int:
        return db.execute(select(func.count()).select_from(model)).scalar_one()

    return [
        ("settings", count(Setting)),
        ("content blocks", count(ContentBlock)),
        ("markets", count(Region)),
        ("services", count(ServiceCategory)),
        ("enquiry form fields", count(FormField)),
        ("FAQ entries", count(FaqEntry)),
        ("user accounts", count(User)),
    ]


def main() -> int:
    say("SmartAWARE — bringing the database up to date\n")

    config = _alembic_config()
    try:
        before = _current_revision()
    except Exception as exc:  # noqa: BLE001 — the message is the useful part
        say(f"Could not reach the database: {exc}")
        say("\nIs Postgres running? In Docker: docker compose up -d db")
        return 1

    pending = _pending(config, before)
    if before is None:
        say("This database has no schema yet — applying everything.")
    elif not pending:
        say(f"Schema is already up to date ({before}).")
    else:
        say(f"Schema is at {before}. {len(pending)} migration(s) to apply:")
        for line in pending:
            say(f"  - {line}")

    if pending or before is None:
        say("\nApplying migrations…")
        command.upgrade(config, "head")
        say(f"Schema now at {_current_revision()}.")

    say("\nSeeding reference data (inserts only; nothing already there is touched)…")
    with SessionLocal() as db:
        created = seed_all(db)

    inserted = sum(
        value
        for section in created.values()
        for value in (section.values() if isinstance(section, dict) else [section])
        if isinstance(value, int)
    )
    say(
        "Nothing to insert — reference data was already complete."
        if inserted == 0
        else f"Inserted {inserted} row(s):"
    )
    if inserted:
        for name, section in created.items():
            rows = section if isinstance(section, dict) else {name: section}
            for label, value in rows.items():
                if isinstance(value, int) and value:
                    say(f"  - {label}: {value}")

    say("\nWhere the database stands:")
    with SessionLocal() as db:
        for label, value in _summary(db):
            say(f"  {label:22} {value}")

        from sqlalchemy import select

        from app.models.enums import UserRole
        from app.models.user import User

        admins = (
            db.execute(select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True)))
            .scalars()
            .all()
        )

    if not admins:
        say("\nNo administrator account yet. Create one to sign in:")
        say("  uv run python scripts/create_admin.py --email you@example.com --generate")

    say("\nDone. The API can be restarted now.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
