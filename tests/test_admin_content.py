"""Admin content management, and who is allowed to do it."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_service import SettingKey, invalidate, set_setting
from app.models.content import CoreValue
from app.models.enums import UserRole


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    invalidate()


@pytest.fixture
def admin_headers(api: TestClient, make_user, login) -> dict[str, str]:
    make_user(UserRole.ADMIN, email="admin@example.com")
    return login("admin@example.com")


@pytest.fixture
def manager_headers(api: TestClient, make_user, login) -> dict[str, str]:
    make_user(UserRole.MANAGER, email="mgr@example.com")
    return login("mgr@example.com")


# --- Permissions (Section 13 item 6) ------------------------------------------


def test_admin_can_manage_content(api: TestClient, admin_headers) -> None:
    assert api.get("/api/v1/admin/content/core-values", headers=admin_headers).status_code == 200


def test_manager_is_refused_by_default(api: TestClient, manager_headers) -> None:
    """Defaulted to Admin-only until SmartAWARE confirms."""
    assert api.get("/api/v1/admin/content/core-values", headers=manager_headers).status_code == 403


def test_manager_is_allowed_once_the_setting_is_enabled(
    api: TestClient, db: Session, manager_headers
) -> None:
    set_setting(db, SettingKey.MANAGER_CAN_MANAGE_CONTENT, True)
    assert api.get("/api/v1/admin/content/core-values", headers=manager_headers).status_code == 200


def test_client_is_refused(api: TestClient, make_user, login) -> None:
    make_user(UserRole.CLIENT, email="client@example.com")
    headers = login("client@example.com")
    assert api.get("/api/v1/admin/content/core-values", headers=headers).status_code == 403


def test_anonymous_is_refused(api: TestClient) -> None:
    assert api.get("/api/v1/admin/content/core-values").status_code == 401


def test_public_endpoints_stay_open(api: TestClient) -> None:
    assert api.get("/api/v1/public/about").status_code == 200


# --- CRUD ---------------------------------------------------------------------


def test_create_edit_and_delete_a_core_value(api: TestClient, admin_headers) -> None:
    created = api.post(
        "/api/v1/admin/content/core-values",
        json={"title": "Innovation", "description": "We improve continuously."},
        headers=admin_headers,
    )
    assert created.status_code == 201
    row_id = created.json()["id"]

    updated = api.patch(
        f"/api/v1/admin/content/core-values/{row_id}",
        json={"description": "Reworded."},
        headers=admin_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "Reworded."
    assert updated.json()["title"] == "Innovation", "partial update must not clear fields"

    assert (
        api.delete(f"/api/v1/admin/content/core-values/{row_id}", headers=admin_headers).status_code
        == 204
    )
    assert (
        api.get(f"/api/v1/admin/content/core-values/{row_id}", headers=admin_headers).status_code
        == 404
    )


def test_new_content_reaches_the_public_page_without_a_deploy(
    api: TestClient, admin_headers
) -> None:
    api.post(
        "/api/v1/admin/content/core-values",
        json={"title": "Innovation", "description": "We improve continuously.", "sort_order": 99},
        headers=admin_headers,
    )
    titles = [v["title"] for v in api.get("/api/v1/public/about").json()["core_values"]]
    assert "Innovation" in titles


def test_reorder_rewrites_sort_order(api: TestClient, db: Session, admin_headers) -> None:
    rows = list(db.execute(select(CoreValue).order_by(CoreValue.sort_order)).scalars())
    reversed_ids = [str(r.id) for r in reversed(rows)]

    response = api.post(
        "/api/v1/admin/content/core-values/reorder",
        json={"ids": reversed_ids},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert [r["id"] for r in response.json()] == reversed_ids

    public = [v["title"] for v in api.get("/api/v1/public/about").json()["core_values"]]
    assert public == [r.title for r in reversed(rows)]


def test_reorder_rejects_unknown_ids(api: TestClient, admin_headers) -> None:
    response = api.post(
        "/api/v1/admin/content/core-values/reorder",
        json={"ids": ["00000000-0000-0000-0000-000000000000"]},
        headers=admin_headers,
    )
    assert response.status_code == 400


def test_admin_listing_includes_unpublished_rows(api: TestClient, admin_headers) -> None:
    """A draft state is useless if the editor cannot see its own drafts."""
    api.post(
        "/api/v1/admin/content/testimonials",
        json={"author_name": "Draft", "quote": "Not yet approved."},
        headers=admin_headers,
    )
    admin_rows = api.get("/api/v1/admin/content/testimonials", headers=admin_headers).json()
    assert "Draft" in [r["author_name"] for r in admin_rows]
    # The draft is the editor's alone until published — the seeded placeholders
    # are published, so assert on the draft rather than on an empty list.
    public = api.get("/api/v1/public/home").json()["testimonials"]
    assert "Draft" not in [r["author_name"] for r in public]


def test_team_and_testimonials_are_unpublished_by_default(api: TestClient, admin_headers) -> None:
    """Publishing a real person or a client quote must be a deliberate act."""
    member = api.post(
        "/api/v1/admin/content/team", json={"name": "A Person"}, headers=admin_headers
    ).json()
    assert member["is_published"] is False

    quote = api.post(
        "/api/v1/admin/content/testimonials",
        json={"author_name": "A Client", "quote": "Good service."},
        headers=admin_headers,
    ).json()
    assert quote["is_published"] is False


# --- Blocks and legal pages ---------------------------------------------------


def test_block_can_be_edited_but_not_created_or_deleted(api: TestClient, admin_headers) -> None:
    """Keys are structural — page templates reference them by name."""
    updated = api.patch(
        "/api/v1/admin/content/blocks/vision",
        json={"body": "Revised vision."},
        headers=admin_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["body"] == "Revised vision."

    assert (
        api.post("/api/v1/admin/content/blocks", json={}, headers=admin_headers).status_code == 405
    )
    assert (
        api.delete("/api/v1/admin/content/blocks/vision", headers=admin_headers).status_code == 405
    )


def test_block_response_carries_its_bullet_list(api: TestClient, admin_headers) -> None:
    block = api.get("/api/v1/admin/content/blocks/mission", headers=admin_headers).json()
    assert len(block["items"]) == 7


def test_bullet_can_be_added_and_removed(api: TestClient, admin_headers) -> None:
    created = api.post(
        "/api/v1/admin/content/list-items",
        json={"block_key": "mission", "text": "A new commitment.", "sort_order": 8},
        headers=admin_headers,
    )
    assert created.status_code == 201
    assert "A new commitment." in api.get("/api/v1/public/about").json()["mission"]["items"]

    api.delete(f"/api/v1/admin/content/list-items/{created.json()['id']}", headers=admin_headers)
    assert "A new commitment." not in api.get("/api/v1/public/about").json()["mission"]["items"]


def test_legal_page_can_be_written_and_published(
    api: TestClient, db: Session, admin_headers
) -> None:
    response = api.patch(
        "/api/v1/admin/content/legal/privacy-policy",
        json={"body": "The real policy text.", "is_published": True, "version": "1.0"},
        headers=admin_headers,
    )
    assert response.status_code == 200

    public = api.get("/api/v1/public/legal/privacy-policy")
    assert public.status_code == 200
    assert public.json()["body"] == "The real policy text."


def test_admin_can_see_unpublished_legal_drafts(api: TestClient, admin_headers) -> None:
    rows = api.get("/api/v1/admin/content/legal", headers=admin_headers).json()
    assert len(rows) == 3
    assert all(r["is_published"] is False for r in rows)
    assert api.get("/api/v1/public/legal").json() == []


def test_legal_pages_cannot_be_created_or_deleted(api: TestClient, admin_headers) -> None:
    assert (
        api.post("/api/v1/admin/content/legal", json={}, headers=admin_headers).status_code == 405
    )
    assert (
        api.delete("/api/v1/admin/content/legal/privacy-policy", headers=admin_headers).status_code
        == 405
    )
