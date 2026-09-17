"""Smart AI chat endpoint — spec Section 4.

One endpoint serves both placements, and it answers anonymously in both. The
bot was never allowed to reach customer data (Section 4.1); now it does not
learn who is asking either, because there is no transcript for a name to be
attached to. The conversation lives in the asker's browser and comes back with
each question so the model has context.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.core import rate_limit
from app.core.deps import DbSession
from app.schemas.chat import AskRequest, AskResponse
from app.services.rag import chat as chat_service
from app.services.rag.client import LlmUnavailable

router = APIRouter(prefix="/public", tags=["public-chat"])

RATE_LIMIT = 30
RATE_WINDOW_SECONDS = 600


@router.post("/chat", response_model=AskResponse, summary="Ask Smart AI")
def ask(payload: AskRequest, request: Request, db: DbSession) -> AskResponse:
    ip = rate_limit.client_ip(request)
    if not rate_limit.check(f"chat:{ip}", limit=RATE_LIMIT, window_seconds=RATE_WINDOW_SECONDS):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many messages. Please wait a moment before asking again.",
        )

    try:
        reply = chat_service.ask(
            db,
            question=payload.question,
            history=[turn.model_dump() for turn in payload.history],
        )
    except LlmUnavailable as exc:
        # Configuration problem rather than a caller problem: say so plainly
        # instead of returning an answer that looks authoritative.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Smart AI is not configured. Please contact us instead.",
        ) from exc

    return AskResponse(
        answer=reply.answer,
        escalated=reply.escalated,
        top_similarity=reply.top_similarity,
    )
