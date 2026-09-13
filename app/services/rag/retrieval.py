"""FAQ retrieval over pgvector."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.faq import FaqEmbedding, FaqEntry


@dataclass
class Match:
    faq_id: object
    question: str
    answer: str
    content: str
    similarity: float


def search(db: Session, query_vector: list[float], *, top_k: int = 5) -> list[Match]:
    """Nearest FAQ entries by cosine similarity.

    pgvector's `<=>` returns cosine *distance*, so similarity is 1 - distance.
    The escalation threshold is expressed as similarity because that is the
    more intuitive direction for whoever tunes it in the Admin Portal.
    """
    distance = FaqEmbedding.embedding.cosine_distance(query_vector).label("distance")

    rows = db.execute(
        select(FaqEmbedding, FaqEntry, distance)
        .join(FaqEntry, FaqEntry.id == FaqEmbedding.faq_id)
        .where(
            FaqEntry.is_deleted.is_(False),
            FaqEntry.is_published.is_(True),
        )
        .order_by(distance)
        .limit(top_k)
    ).all()

    return [
        Match(
            faq_id=entry.id,
            question=entry.question,
            answer=entry.answer,
            content=embedding.content,
            similarity=1.0 - float(dist),
        )
        for embedding, entry, dist in rows
    ]


def build_context(matches: list[Match]) -> str:
    return "\n\n".join(
        f"[{index}] Q: {match.question}\nA: {match.answer}"
        for index, match in enumerate(matches, start=1)
    )
