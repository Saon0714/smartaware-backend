"""Incremental FAQ re-indexing — spec Section 4.4.

The requirement is specific: embed only what is new or changed, remove
embeddings for deleted entries, and never re-embed the whole pool. These tests
assert on which entries were sent to the embedding API, because that is the
only thing that actually proves the job is incremental.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.faq import FaqEmbedding, FaqEntry
from app.services.rag.indexer import reindex


@pytest.fixture
def faqs(db: Session) -> list[FaqEntry]:
    entries = [
        FaqEntry(
            question="How do I file a Self Assessment return?",
            answer="We prepare and submit it on your behalf.",
        ),
        FaqEntry(
            question="Do you offer payroll services?",
            answer="Yes, monthly and weekly payroll processing.",
        ),
        FaqEntry(
            question="Which countries do you work in?", answer="The UK, India, the UAE and Oman."
        ),
    ]
    db.add_all(entries)
    db.flush()
    return entries


def _age_index(db: Session, entry: FaqEntry) -> None:
    """Make an entry's index look older than a subsequent edit.

    Postgres `now()` is the transaction's start time, so everything written
    inside one test transaction carries an identical timestamp. Production runs
    each edit and each index in its own transaction, where the clock genuinely
    advances; here that has to be simulated.
    """
    entry.indexed_at = datetime.now(UTC) - timedelta(hours=1)
    db.flush()


def _embedded_count(db: Session) -> int:
    return db.execute(select(func.count()).select_from(FaqEmbedding)).scalar_one()


def test_first_run_embeds_everything(db: Session, faqs, ai) -> None:
    report = reindex(db, ai)

    assert report.embedded == 3
    assert report.removed == 0
    assert _embedded_count(db) == 3
    assert all(entry.indexed_at is not None for entry in faqs)


def test_second_run_embeds_nothing(db: Session, faqs, ai) -> None:
    """The headline requirement: a full re-embed every night is not acceptable."""
    reindex(db, ai)
    ai.embed_calls.clear()

    report = reindex(db, ai)

    assert report.embedded == 0
    assert report.skipped == 3
    assert ai.embed_calls == [], "no text should reach the embedding API"
    assert report.was_noop is True


def test_only_the_edited_entry_is_re_embedded(db: Session, faqs, ai) -> None:
    reindex(db, ai)
    ai.embed_calls.clear()

    _age_index(db, faqs[1])
    faqs[1].answer = "Yes — weekly, fortnightly and monthly payroll."
    db.flush()

    report = reindex(db, ai)

    assert report.embedded == 1
    assert report.skipped == 2
    sent = [text for call in ai.embed_calls for text in call]
    assert len(sent) == 1
    assert "fortnightly" in sent[0]


def test_editing_replaces_the_old_vector(db: Session, faqs, ai) -> None:
    """Otherwise an edited entry keeps matching on its previous wording."""
    reindex(db, ai)
    original = db.execute(
        select(FaqEmbedding).where(FaqEmbedding.faq_id == faqs[0].id)
    ).scalar_one()
    original_content = original.content

    _age_index(db, faqs[0])
    faqs[0].answer = "Completely different answer about company accounts."
    db.flush()
    reindex(db, ai)

    rows = db.execute(select(FaqEmbedding).where(FaqEmbedding.faq_id == faqs[0].id)).scalars().all()
    assert len(rows) == 1, "the previous vector must be replaced, not added to"
    assert rows[0].content != original_content


def test_deleting_removes_its_embeddings(db: Session, faqs, ai) -> None:
    reindex(db, ai)
    assert _embedded_count(db) == 3

    faqs[2].is_deleted = True
    faqs[2].is_published = False
    db.flush()

    report = reindex(db, ai)

    assert report.removed == 1
    assert _embedded_count(db) == 2
    assert db.execute(select(FaqEmbedding).where(FaqEmbedding.faq_id == faqs[2].id)).first() is None


def test_unpublishing_also_retires_the_vector(db: Session, faqs, ai) -> None:
    """An unpublished entry must stop being retrievable, not merely hidden."""
    reindex(db, ai)
    faqs[0].is_published = False
    db.flush()

    reindex(db, ai)
    assert _embedded_count(db) == 2


def test_restoring_a_deleted_entry_re_embeds_it(db: Session, faqs, ai) -> None:
    reindex(db, ai)
    faqs[0].is_deleted = True
    faqs[0].is_published = False
    db.flush()
    reindex(db, ai)
    assert _embedded_count(db) == 2

    faqs[0].is_deleted = False
    faqs[0].is_published = True
    faqs[0].indexed_at = None  # what the restore endpoint does
    db.flush()

    report = reindex(db, ai)
    assert report.embedded == 1
    assert _embedded_count(db) == 3


def test_run_with_no_faqs_is_a_clean_noop(db: Session, ai) -> None:
    report = reindex(db, ai)
    assert report.as_dict() == {
        "embedded": 0,
        "removed": 0,
        "skipped": 0,
        "failed": 0,
        "noop": True,
    }
    assert ai.embed_calls == []


def test_a_failing_batch_leaves_entries_stale_for_the_next_run(db: Session, faqs, ai) -> None:
    """A transient API failure must not mark entries as indexed."""
    ai.fail_embed = True
    report = reindex(db, ai)

    assert report.failed == 3
    assert report.embedded == 0
    assert all(entry.indexed_at is None for entry in faqs)

    ai.fail_embed = False
    recovered = reindex(db, ai)
    assert recovered.embedded == 3


def test_a_stale_entry_is_one_whose_update_is_newer_than_its_index(db: Session, faqs, ai) -> None:
    """The mechanism itself, stated plainly."""
    reindex(db, ai)
    entry = faqs[0]
    assert entry.indexed_at is not None
    assert entry.updated_at <= entry.indexed_at

    entry.indexed_at = datetime.now(UTC) - timedelta(days=1)
    db.flush()

    report = reindex(db, ai)
    assert report.embedded == 1
