"""Smart AI chat endpoint — spec Section 4.

One endpoint serves both placements. The public widget calls it anonymously;
the portal widget calls it with credentials so the transcript can be attributed
(Section 4.5). Either way the answer is drawn only from the FAQ — the
authenticated case gains attribution, never data access (Section 4.1).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.deps import DbSession
from app.models.enums import ChatSurface
from app.schemas.chat import AskRequest, AskResponse
from app.services import auth_service
from app.services.rag import chat as chat_service
from app.services.rag.client import LlmUnavailable

router = APIRouter(prefix="/public", tags=["public-chat"])

_optional_bearer = HTTPBearer(auto_error=False)

RATE_LIMIT = 30
RATE_WINDOW_SECONDS = 600


def _viewer(
    db: Session,
    credentials: HTTPAuthorizationCredentials | None,
) -> tuple[ChatSurface, object, object]:
    """Identify the caller if they happen to be signed in.

    Authentication is optional: the widget is on public pages too. A bad token
    is treated as anonymous rather than rejected — the chatbot should keep
    working while a session quietly expires.
    """
    if credentials is None:
        return ChatSurface.PUBLIC, None, None
    try:
        user = auth_service.user_from_token(db, credentials.credentials, "access")
    except auth_service.AuthError:
        return ChatSurface.PUBLIC, None, None

    client_id = user.client.id if user.client else None
    return ChatSurface.PORTAL, user.id, client_id


@router.post("/chat", response_model=AskResponse, summary="Ask Smart AI")
def ask(
    payload: AskRequest,
    request: Request,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)] = None,
) -> AskResponse:
    ip = rate_limit.client_ip(request)
    if not rate_limit.check(f"chat:{ip}", limit=RATE_LIMIT, window_seconds=RATE_WINDOW_SECONDS):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many messages. Please wait a moment before asking again.",
        )

    surface, user_id, client_id = _viewer(db, credentials)

    try:
        reply = chat_service.ask(
            db,
            question=payload.question,
            session_token=payload.session_token,
            surface=surface,
            user_id=user_id,
            client_id=client_id,
        )
    except LlmUnavailable as exc:
        # Configuration problem rather than a caller problem: say so plainly
        # instead of returning an answer that looks authoritative.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Smart AI is not configured. Please contact us instead.",
        ) from exc

    return AskResponse(
        session_token=reply.session_token,
        answer=reply.answer,
        escalated=reply.escalated,
        top_similarity=reply.top_similarity,
    )
