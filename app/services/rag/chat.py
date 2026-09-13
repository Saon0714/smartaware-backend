"""The Smart AI conversation flow — spec Section 4.

Scope is FAQ-only. Section 4.1 is explicit that the bot must not reach customer
data even when used inside the authenticated portal, so nothing from the
signed-in user's account is ever retrieved or placed in the prompt. The session
is associated with their account purely so transcripts can be attributed
(Section 4.5).
"""

from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_service import SettingKey, get_setting
from app.models.chat import ChatMessage, ChatSession
from app.models.enums import ChatRole, ChatSurface
from app.services.rag import retrieval
from app.services.rag.client import AiClient, LlmUnavailable, get_client

logger = logging.getLogger(__name__)

#: Shown when retrieval finds nothing relevant enough. Section 4.2: a plain UI
#: fallback, with no ticket raised and no staff notified.
ESCALATION_MESSAGE = (
    "I don't have information on that in our FAQ. Please contact us and a "
    "member of the SmartAWARE team will be glad to help."
)

UNAVAILABLE_MESSAGE = (
    "Smart AI is temporarily unavailable. Please contact us and a member of "
    "the SmartAWARE team will be glad to help."
)

MAX_QUESTION_LENGTH = 1000


@dataclass
class ChatReply:
    session_token: str
    answer: str
    escalated: bool
    top_similarity: float | None


def get_or_create_session(
    db: Session,
    *,
    session_token: str | None,
    surface: ChatSurface,
    user_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
) -> ChatSession:
    if session_token:
        existing = db.execute(
            select(ChatSession).where(ChatSession.session_token == session_token)
        ).scalar_one_or_none()
        if existing is not None:
            # Attribute a session that began anonymously and then signed in.
            if user_id and existing.user_id is None:
                existing.user_id = user_id
                existing.client_id = client_id
                existing.surface = surface
            existing.last_activity_at = datetime.now(UTC)
            return existing

    session = ChatSession(
        session_token=secrets.token_urlsafe(24),
        surface=surface,
        user_id=user_id,
        client_id=client_id,
        last_activity_at=datetime.now(UTC),
    )
    db.add(session)
    db.flush()
    return session


def _history(db: Session, session: ChatSession) -> list[dict]:
    rows = db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at)
    ).scalars()
    return [{"role": row.role.value, "content": row.content} for row in rows]


def ask(
    db: Session,
    *,
    question: str,
    session_token: str | None,
    surface: ChatSurface,
    user_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    client: AiClient | None = None,
) -> ChatReply:
    question = question.strip()[:MAX_QUESTION_LENGTH]

    session = get_or_create_session(
        db,
        session_token=session_token,
        surface=surface,
        user_id=user_id,
        client_id=client_id,
    )
    history = _history(db, session)

    db.add(ChatMessage(session_id=session.id, role=ChatRole.USER, content=question))

    threshold = float(get_setting(db, SettingKey.CHAT_SIMILARITY_THRESHOLD, 0.75))
    top_k = int(get_setting(db, SettingKey.CHAT_TOP_K, 5))

    ai = client or get_client()

    try:
        query_vector = ai.embed([question])[0]
        matches = retrieval.search(db, query_vector, top_k=top_k)
    except LlmUnavailable:
        raise
    except Exception:
        logger.exception("FAQ retrieval failed")
        matches = []

    best = matches[0].similarity if matches else None
    escalated = best is None or best < threshold

    if escalated:
        # No model call on escalation: there is nothing relevant to ground an
        # answer in, so asking anyway would only invite invention.
        answer = ESCALATION_MESSAGE
    else:
        try:
            answer = ai.answer(question, retrieval.build_context(matches), history)
        except Exception:
            logger.exception("Chat completion failed")
            answer = UNAVAILABLE_MESSAGE
            escalated = True

    db.add(
        ChatMessage(
            session_id=session.id,
            role=ChatRole.ASSISTANT,
            content=answer,
            escalated=escalated,
            top_similarity=best,
        )
    )
    db.commit()

    return ChatReply(
        session_token=session.session_token,
        answer=answer,
        escalated=escalated,
        top_similarity=best,
    )


def purge_expired_logs(db: Session) -> int:
    """Delete transcripts past the configured retention window.

    Section 4.5 requires the window to be admin-editable rather than a
    hardcoded constant, so it is read at run time.
    """
    from datetime import timedelta

    days = int(get_setting(db, SettingKey.CHAT_RETENTION_DAYS, 30))
    cutoff = datetime.now(UTC) - timedelta(days=days)

    sessions = list(
        db.execute(select(ChatSession).where(ChatSession.created_at < cutoff)).scalars()
    )
    for session in sessions:
        # Messages cascade with the session.
        db.delete(session)
    db.commit()

    logger.info("Purged %s chat session(s) older than %s days.", len(sessions), days)
    return len(sessions)
