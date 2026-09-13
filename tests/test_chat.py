"""Smart AI conversation behaviour — spec Section 4."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.settings_service import SettingKey, invalidate, set_setting
from app.models.chat import ChatMessage, ChatSession
from app.models.enums import ChatSurface, UserRole
from app.models.faq import FaqEntry
from app.services.rag import chat as chat_service
from app.services.rag.chat import ESCALATION_MESSAGE
from app.services.rag.indexer import reindex

TEST_CLIENT_IP = "testclient"


@pytest.fixture(autouse=True)
def _reset() -> None:
    invalidate()
    rate_limit.reset(f"chat:{TEST_CLIENT_IP}")


@pytest.fixture
def indexed_faqs(seeded_db: Session, ai) -> None:
    """Seeded, because the escalation threshold and retention window are
    settings rows rather than constants."""
    db = seeded_db
    db.add_all(
        [
            FaqEntry(
                question="Do you offer payroll services?",
                answer="Yes, we provide weekly and monthly payroll processing.",
            ),
            FaqEntry(
                question="Which countries do you work in?",
                answer="We work in the UK, India, the UAE and Oman.",
            ),
            FaqEntry(
                question="How do I file a Self Assessment tax return?",
                answer="We prepare and submit your Self Assessment return.",
            ),
        ]
    )
    db.flush()
    reindex(db, ai)


def _ask(db: Session, question: str, ai, **kwargs):
    return chat_service.ask(
        db, question=question, session_token=None, surface=ChatSurface.PUBLIC, client=ai, **kwargs
    )


# --- Answering and escalation ---------------------------------------------------


def test_a_relevant_question_is_answered_from_the_faq(db: Session, indexed_faqs, ai) -> None:
    set_setting(db, SettingKey.CHAT_SIMILARITY_THRESHOLD, 0.3)

    reply = _ask(db, "Do you offer payroll services?", ai)

    assert reply.escalated is False
    assert ai.answer_calls, "the model should have been asked"
    _question, context = ai.answer_calls[0]
    assert "payroll" in context.lower()


def test_an_unrelated_question_escalates(db: Session, indexed_faqs, ai) -> None:
    """Section 4.2: a plain 'please contact us' fallback."""
    set_setting(db, SettingKey.CHAT_SIMILARITY_THRESHOLD, 0.9)

    reply = _ask(db, "What is the airspeed velocity of a swallow?", ai)

    assert reply.escalated is True
    assert reply.answer == ESCALATION_MESSAGE


def test_escalation_does_not_call_the_model(db: Session, indexed_faqs, ai) -> None:
    """Nothing relevant to ground an answer in, so asking anyway would only
    invite invention — and cost money."""
    set_setting(db, SettingKey.CHAT_SIMILARITY_THRESHOLD, 0.99)

    _ask(db, "Something entirely unrelated to tax", ai)

    assert ai.answer_calls == []


def test_the_threshold_is_configurable_not_hardcoded(db: Session, indexed_faqs, ai) -> None:
    """Section 13 item 7 is unconfirmed, so it has to be tunable."""
    question = "Do you offer payroll services?"

    set_setting(db, SettingKey.CHAT_SIMILARITY_THRESHOLD, 0.99)
    assert _ask(db, question, ai).escalated is True

    set_setting(db, SettingKey.CHAT_SIMILARITY_THRESHOLD, 0.3)
    assert _ask(db, question, ai).escalated is False


def test_with_no_faq_content_everything_escalates(seeded_db: Session, ai) -> None:
    reply = _ask(seeded_db, "Do you offer payroll services?", ai)
    assert reply.escalated is True
    assert reply.top_similarity is None


def test_a_model_failure_degrades_gracefully(db: Session, indexed_faqs, ai) -> None:
    set_setting(db, SettingKey.CHAT_SIMILARITY_THRESHOLD, 0.3)
    ai.fail_answer = True

    reply = _ask(db, "Do you offer payroll services?", ai)

    assert reply.escalated is True
    assert "contact us" in reply.answer.lower()


# --- Transcripts (Section 4.5) ---------------------------------------------------


def test_both_sides_of_the_exchange_are_logged(db: Session, indexed_faqs, ai) -> None:
    set_setting(db, SettingKey.CHAT_SIMILARITY_THRESHOLD, 0.3)
    reply = _ask(db, "Do you offer payroll services?", ai)

    session = db.execute(
        select(ChatSession).where(ChatSession.session_token == reply.session_token)
    ).scalar_one()
    messages = (
        db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.created_at)
        )
        .scalars()
        .all()
    )

    assert [m.role.value for m in messages] == ["user", "assistant"]
    assert messages[1].top_similarity is not None


def test_a_conversation_continues_in_one_session(db: Session, indexed_faqs, ai) -> None:
    first = _ask(db, "Do you offer payroll services?", ai)
    second = chat_service.ask(
        db,
        question="And in the UAE?",
        session_token=first.session_token,
        surface=ChatSurface.PUBLIC,
        client=ai,
    )

    assert second.session_token == first.session_token
    assert db.execute(select(func.count()).select_from(ChatSession)).scalar_one() == 1
    assert db.execute(select(func.count()).select_from(ChatMessage)).scalar_one() == 4


def test_an_unknown_session_token_starts_a_new_session(db: Session, indexed_faqs, ai) -> None:
    reply = chat_service.ask(
        db,
        question="Hello",
        session_token="not-a-real-token",
        surface=ChatSurface.PUBLIC,
        client=ai,
    )
    assert reply.session_token != "not-a-real-token"


def test_retention_purge_uses_the_configured_window(db: Session, indexed_faqs, ai) -> None:
    """Section 4.5 requires the window to be admin-editable."""
    reply = _ask(db, "Do you offer payroll services?", ai)
    session = db.execute(
        select(ChatSession).where(ChatSession.session_token == reply.session_token)
    ).scalar_one()

    assert chat_service.purge_expired_logs(db) == 0

    session.created_at = datetime.now(UTC) - timedelta(days=40)
    db.flush()

    assert chat_service.purge_expired_logs(db) == 1
    assert db.execute(select(func.count()).select_from(ChatSession)).scalar_one() == 0
    assert db.execute(select(func.count()).select_from(ChatMessage)).scalar_one() == 0


def test_shortening_retention_purges_more(db: Session, indexed_faqs, ai) -> None:
    reply = _ask(db, "Do you offer payroll services?", ai)
    session = db.execute(
        select(ChatSession).where(ChatSession.session_token == reply.session_token)
    ).scalar_one()
    session.created_at = datetime.now(UTC) - timedelta(days=10)
    db.flush()

    assert chat_service.purge_expired_logs(db) == 0

    set_setting(db, SettingKey.CHAT_RETENTION_DAYS, 7)
    assert chat_service.purge_expired_logs(db) == 1


# --- The HTTP endpoint ------------------------------------------------------------


def test_the_widget_works_without_signing_in(api: TestClient, ai) -> None:
    response = api.post("/api/v1/public/chat", json={"question": "Hello"})
    assert response.status_code == 200
    assert response.json()["session_token"]


def test_a_signed_in_visitor_has_their_transcript_attributed(
    api: TestClient, db: Session, make_user, login, ai
) -> None:
    """Section 4.5 wants portal conversations linked to the account."""
    user, client = make_user(UserRole.CLIENT, email="client@example.com")
    headers = login("client@example.com")

    response = api.post("/api/v1/public/chat", json={"question": "Hello"}, headers=headers)
    assert response.status_code == 200

    session = db.execute(select(ChatSession)).scalars().one()
    assert session.surface is ChatSurface.PORTAL
    assert session.user_id == user.id
    assert session.client_id == client.id


def test_an_expired_session_still_gets_an_answer(api: TestClient, ai) -> None:
    """The widget is on public pages too, so a stale token must not break it."""
    response = api.post(
        "/api/v1/public/chat",
        json={"question": "Hello"},
        headers={"Authorization": "Bearer not-a-valid-token"},
    )
    assert response.status_code == 200


def test_chat_is_rate_limited(api: TestClient, ai) -> None:
    for _ in range(30):
        api.post("/api/v1/public/chat", json={"question": "Hi"})
    assert api.post("/api/v1/public/chat", json={"question": "Hi"}).status_code == 429


def test_an_empty_question_is_rejected(api: TestClient, ai) -> None:
    assert api.post("/api/v1/public/chat", json={"question": ""}).status_code == 422
