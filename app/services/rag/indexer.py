"""Incremental FAQ re-indexing — spec Section 4.4.

The nightly job must embed only what changed and must never re-embed the whole
pool. Three states drive that, all derivable from the FAQ row itself:

  * deleted   -> soft-deleted entries have their embeddings removed
  * stale     -> indexed_at is null, or updated_at is newer than indexed_at
  * current   -> left completely alone

If nothing changed the job still runs and exits as a no-op. Section 4.4 is
explicit that execution must not be skipped, because skipping would let a late
edit sit unindexed until something else happened to change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.faq import FaqEmbedding, FaqEntry
from app.services.rag.client import AiClient, get_client

logger = logging.getLogger(__name__)

#: Entries embedded per API call.
BATCH_SIZE = 64


@dataclass
class IndexReport:
    embedded: int = 0
    removed: int = 0
    skipped: int = 0
    failed: int = 0

    @property
    def was_noop(self) -> bool:
        return self.embedded == 0 and self.removed == 0

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "embedded": self.embedded,
            "removed": self.removed,
            "skipped": self.skipped,
            "failed": self.failed,
            "noop": self.was_noop,
        }


def embedding_text(entry: FaqEntry) -> str:
    """What actually gets embedded.

    Question and answer together: a question alone matches phrasing, and an
    answer alone loses the topic. FAQ entries are short enough that splitting
    into multiple chunks would separate a question from its answer.
    """
    return f"Q: {entry.question}\nA: {entry.answer}"


def _stale_entries(db: Session) -> list[FaqEntry]:
    return list(
        db.execute(
            select(FaqEntry)
            .where(
                FaqEntry.is_deleted.is_(False),
                FaqEntry.is_published.is_(True),
                or_(
                    FaqEntry.indexed_at.is_(None),
                    FaqEntry.updated_at > FaqEntry.indexed_at,
                ),
            )
            .order_by(FaqEntry.updated_at)
        ).scalars()
    )


def _retired_entry_ids(db: Session) -> list:
    """Entries with embeddings that should no longer have any."""
    return list(
        db.execute(
            select(FaqEntry.id)
            .join(FaqEmbedding, FaqEmbedding.faq_id == FaqEntry.id)
            .where(
                or_(
                    FaqEntry.is_deleted.is_(True),
                    FaqEntry.is_published.is_(False),
                )
            )
            .distinct()
        ).scalars()
    )


def reindex(db: Session, client: AiClient | None = None) -> IndexReport:
    """Process the delta. Safe to run when nothing has changed."""
    report = IndexReport()

    retired = _retired_entry_ids(db)
    if retired:
        db.execute(delete(FaqEmbedding).where(FaqEmbedding.faq_id.in_(retired)))
        report.removed = len(retired)

    stale = _stale_entries(db)
    total = db.execute(select(FaqEntry).where(FaqEntry.is_deleted.is_(False))).scalars()
    report.skipped = len(list(total)) - len(stale)

    if not stale:
        db.commit()
        logger.info("FAQ re-index: nothing to do (%s)", report.as_dict())
        return report

    ai = client or get_client()

    for start in range(0, len(stale), BATCH_SIZE):
        batch = stale[start : start + BATCH_SIZE]
        try:
            vectors = ai.embed([embedding_text(entry) for entry in batch])
        except Exception:
            # One failing batch must not abandon the rest, and the entries stay
            # stale so the next run retries them.
            logger.exception("Embedding batch failed; leaving entries stale.")
            report.failed += len(batch)
            continue

        # The database clock, not the application's. `updated_at` is set by
        # the database, and staleness is decided by comparing the two — reading
        # them from different clocks would make a drifting app server either
        # miss edits or re-embed constantly.
        now = func.now()
        for entry, vector in zip(batch, vectors, strict=True):
            # Replace rather than append, or an edited entry would keep matching
            # on its previous wording.
            db.execute(delete(FaqEmbedding).where(FaqEmbedding.faq_id == entry.id))
            db.add(
                FaqEmbedding(
                    faq_id=entry.id,
                    chunk_index=0,
                    content=embedding_text(entry),
                    embedding=vector,
                    model=settings.OPENAI_EMBEDDING_MODEL,
                )
            )
            entry.indexed_at = now
            report.embedded += 1

    db.commit()
    logger.info("FAQ re-index complete: %s", report.as_dict())
    return report
