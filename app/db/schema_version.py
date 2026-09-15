"""Is the database's schema the one this code expects?

A database left behind a migration fails in a way that tells you nothing: the
ORM selects a column the table does not have, and every page that touches it
returns 500. The message naming the missing column is in the server log, if
anyone thinks to look, and nowhere else.

That is the normal state of affairs after a `git pull`, so it is worth saying
out loud at startup rather than leaving to be diagnosed.

Best effort throughout. A database that cannot be reached is a different
problem, and this must not be the thing that stops the process starting — the
health endpoint is more useful up than down.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.db.session import engine

logger = logging.getLogger(__name__)

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@dataclass(frozen=True)
class SchemaVersion:
    applied: str | None
    expected: str | None

    @property
    def status(self) -> str:
        if self.applied is None or self.expected is None:
            return "unknown"
        return "ok" if self.applied == self.expected else "stale"


def read() -> SchemaVersion:
    applied = expected = None

    try:
        expected = ScriptDirectory.from_config(Config(str(_ALEMBIC_INI))).get_current_head()
    except Exception:
        logger.exception("Could not read the migration history")

    try:
        with engine.connect() as connection:
            applied = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
    except Exception:
        # No alembic_version table means migrations have never been run here,
        # which is the same conversation as being behind on them.
        logger.debug("Could not read alembic_version", exc_info=True)

    return SchemaVersion(applied=applied, expected=expected)


def warn_if_stale() -> SchemaVersion:
    """Log an unmissable line when the schema is not what the code expects."""
    version = read()
    if version.status == "stale":
        logger.error(
            "DATABASE SCHEMA IS OUT OF DATE — this build expects migration %s but the "
            "database is at %s. Every page that reads a changed table will return 500 "
            "until you run:  alembic upgrade head",
            version.expected,
            version.applied or "(no migrations applied)",
        )
    return version
