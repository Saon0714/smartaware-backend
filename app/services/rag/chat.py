"""The Smart AI conversation flow — spec Section 4.

Scope is FAQ-only. Section 4.1 is explicit that the bot must not reach customer
data even when used inside the authenticated portal, so nothing from the
signed-in user's account is ever retrieved or placed in the prompt.

Nothing said to it is written down. A question is answered and forgotten: the
conversation exists in the asker's own browser and is sent back with each turn
so the model has context, and the server keeps no record of who asked what. A
person who wants SmartAWARE to see their question sends an enquiry, which is a
deliberate act with a form in front of them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.settings_service import SettingKey, get_setting
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

#: How much of the conversation is sent to the model. It arrives from the
#: browser, so it is capped here rather than trusted: long enough to follow a
#: thread, short enough that nobody can use the endpoint to relay an essay.
MAX_HISTORY_TURNS = 12
MAX_HISTORY_CHARS = 4000


@dataclass
class ChatReply:
    answer: str
    escalated: bool
    top_similarity: float | None


def _clean_history(history: list[dict] | None) -> list[dict]:
    turns = [
        {"role": turn["role"], "content": str(turn["content"]).strip()[:MAX_HISTORY_CHARS]}
        for turn in (history or [])
        if str(turn.get("content", "")).strip()
    ]
    return turns[-MAX_HISTORY_TURNS:]


def ask(
    db: Session,
    *,
    question: str,
    history: list[dict] | None = None,
    client: AiClient | None = None,
) -> ChatReply:
    question = question.strip()[:MAX_QUESTION_LENGTH]

    threshold = float(get_setting(db, SettingKey.CHAT_SIMILARITY_THRESHOLD, 0.75))
    top_k = int(get_setting(db, SettingKey.CHAT_TOP_K, 5))

    ai = client or get_client()

    try:
        query_vector = ai.embed([question])[0]
        matches = retrieval.search(db, query_vector, top_k=top_k)
    except LlmUnavailable:
        raise
    except Exception:
        # Logged without the question: a traceback is a record too.
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
            answer = ai.answer(question, retrieval.build_context(matches), _clean_history(history))
        except Exception:
            logger.exception("Chat completion failed")
            answer = UNAVAILABLE_MESSAGE
            escalated = True

    return ChatReply(answer=answer, escalated=escalated, top_similarity=best)
