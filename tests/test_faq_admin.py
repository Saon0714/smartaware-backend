"""FAQ management and chat transcript visibility."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.settings_service import SettingKey, invalidate, set_setting
from app.models.enums import ChatSurface, UserRole
from app.models.faq import FaqEntry
from app.services.rag import chat as chat_service


@pytest.fixture(autouse=True)
def _reset() -> None:
    invalidate()


@pytest.fixture
def admin_headers(api: TestClient, make_user, login) -> dict[str, str]:
    make_user(UserRole.ADMIN, email="admin@example.com")
    return login("admin@example.com")


@pytest.fixture
def manager_headers(api: TestClient, make_user, login) -> dict[str, str]:
    make_user(UserRole.MANAGER, email="mgr@example.com")
    return login("mgr@example.com")


# --- Content management (Section 4.3) --------------------------------------------


def test_faq_can_be_created_edited_and_deleted_without_code(api: TestClient, admin_headers) -> None:
    created = api.post(
        "/api/v1/admin/faq",
        json={"question": "Do you work weekends?", "answer": "By arrangement."},
        headers=admin_headers,
    )
    assert created.status_code == 201
    entry_id = created.json()["id"]
    assert created.json()["indexed_at"] is None, "queued for the next index run"

    updated = api.patch(
        f"/api/v1/admin/faq/{entry_id}",
        json={"answer": "Yes, by prior arrangement."},
        headers=admin_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["answer"] == "Yes, by prior arrangement."
    assert updated.json()["question"] == "Do you work weekends?"

    deleted = api.delete(f"/api/v1/admin/faq/{entry_id}", headers=admin_headers)
    assert deleted.json()["is_published"] is False


def test_delete_is_soft(api: TestClient, db: Session, admin_headers) -> None:
    """Section 4.4 depends on it: a hard delete would orphan the entry's
    vectors with nothing left to tell the indexer to remove them."""
    created = api.post(
        "/api/v1/admin/faq",
        json={"question": "Is this a question?", "answer": "It is."},
        headers=admin_headers,
    ).json()
    api.delete(f"/api/v1/admin/faq/{created['id']}", headers=admin_headers)

    row = db.get(FaqEntry, created["id"])
    assert row is not None
    assert row.is_deleted is True
    assert row.deleted_at is not None


def test_deleted_entries_are_hidden_but_recoverable(api: TestClient, admin_headers) -> None:
    created = api.post(
        "/api/v1/admin/faq",
        json={"question": "Is this a question?", "answer": "It is."},
        headers=admin_headers,
    ).json()
    api.delete(f"/api/v1/admin/faq/{created['id']}", headers=admin_headers)

    assert created["id"] not in [
        r["id"] for r in api.get("/api/v1/admin/faq", headers=admin_headers).json()
    ]
    assert created["id"] in [
        r["id"]
        for r in api.get("/api/v1/admin/faq?include_deleted=true", headers=admin_headers).json()
    ]

    restored = api.post(f"/api/v1/admin/faq/{created['id']}/restore", headers=admin_headers)
    assert restored.json()["is_deleted"] is False
    assert restored.json()["indexed_at"] is None, "must be re-embedded"


def test_index_status_reports_the_pending_delta(api: TestClient, admin_headers) -> None:
    """So an administrator can see the nightly job has work queued."""
    before = api.get("/api/v1/admin/faq-index/status", headers=admin_headers).json()

    api.post(
        "/api/v1/admin/faq",
        json={"question": "New question?", "answer": "New answer."},
        headers=admin_headers,
    )

    after = api.get("/api/v1/admin/faq-index/status", headers=admin_headers).json()
    # Relative, not absolute: the seed ships starter FAQ entries, which are
    # themselves pending until the first index run.
    assert after["pending"] == before["pending"] + 1
    assert after["total"] == before["total"] + 1


# --- Permissions -----------------------------------------------------------------


def test_manager_cannot_manage_faq_by_default(api: TestClient, manager_headers) -> None:
    """Section 13 item 6, defaulted to Admin-only."""
    assert api.get("/api/v1/admin/faq", headers=manager_headers).status_code == 403


def test_manager_can_manage_faq_once_enabled(api: TestClient, db: Session, manager_headers) -> None:
    set_setting(db, SettingKey.MANAGER_CAN_MANAGE_CONTENT, True)
    assert api.get("/api/v1/admin/faq", headers=manager_headers).status_code == 200


def test_client_and_anonymous_cannot_manage_faq(api: TestClient, make_user, login) -> None:
    make_user(UserRole.CLIENT, email="client@example.com")
    assert api.get("/api/v1/admin/faq", headers=login("client@example.com")).status_code == 403
    assert api.get("/api/v1/admin/faq").status_code == 401


# --- Chat transcript visibility (Section 13 item 8) --------------------------------


@pytest.fixture
def a_conversation(api: TestClient, db: Session, ai) -> None:
    chat_service.ask(
        db,
        question="Hello",
        session_token=None,
        surface=ChatSurface.PUBLIC,
        client=ai,
    )


def test_admin_may_read_transcripts_by_default(
    api: TestClient, a_conversation, admin_headers
) -> None:
    rows = api.get("/api/v1/admin/chat-sessions", headers=admin_headers).json()
    assert len(rows) == 1
    assert rows[0]["message_count"] == 2

    detail = api.get(f"/api/v1/admin/chat-sessions/{rows[0]['id']}", headers=admin_headers).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]


def test_manager_may_not_read_transcripts_by_default(
    api: TestClient, a_conversation, manager_headers
) -> None:
    assert api.get("/api/v1/admin/chat-sessions", headers=manager_headers).status_code == 403


def test_manager_may_read_when_the_setting_allows(
    api: TestClient, db: Session, a_conversation, manager_headers
) -> None:
    set_setting(db, SettingKey.CHAT_LOGS_VISIBLE_TO, "admin_and_manager")
    assert api.get("/api/v1/admin/chat-sessions", headers=manager_headers).status_code == 200


def test_nobody_can_read_when_disabled(
    api: TestClient, db: Session, a_conversation, admin_headers
) -> None:
    """Including the administrator — the setting means what it says."""
    set_setting(db, SettingKey.CHAT_LOGS_VISIBLE_TO, "nobody")
    assert api.get("/api/v1/admin/chat-sessions", headers=admin_headers).status_code == 403


def test_client_can_never_read_transcripts(
    api: TestClient, a_conversation, make_user, login
) -> None:
    make_user(UserRole.CLIENT, email="client@example.com")
    assert (
        api.get("/api/v1/admin/chat-sessions", headers=login("client@example.com")).status_code
        == 403
    )
