"""The Section 6.1 permission matrix, enforced server-side.

Spec Section 9 requires role checks at the API layer and treats UI hiding as
insufficient. These tests therefore assert on the matrix itself and, where a
rule is easy to get wrong, on the HTTP response.
"""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.permissions import Permission, effective_permissions, has_permission
from app.core.settings_service import SettingKey, invalidate, set_setting
from app.models.enums import UserRole


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    invalidate()


# --- Tasks (Section 6.1) -----------------------------------------------------


@pytest.mark.parametrize(
    ("role", "permission", "expected"),
    [
        (UserRole.ADMIN, Permission.TASK_CREATE, True),
        (UserRole.ADMIN, Permission.TASK_UPDATE, True),
        (UserRole.ADMIN, Permission.TASK_COMPLETE, True),
        (UserRole.ADMIN, Permission.TASK_DELETE, True),
        (UserRole.ADMIN, Permission.CLIENT_ASSIGN_MANAGER, True),
        (UserRole.MANAGER, Permission.TASK_CREATE, True),
        (UserRole.MANAGER, Permission.TASK_UPDATE, True),
        (UserRole.MANAGER, Permission.TASK_COMPLETE, True),
        # The headline restriction: deletion is Admin-only.
        (UserRole.MANAGER, Permission.TASK_DELETE, False),
        (UserRole.MANAGER, Permission.CLIENT_ASSIGN_MANAGER, False),
        (UserRole.MANAGER, Permission.SETTINGS_MANAGE, False),
        (UserRole.MANAGER, Permission.INVITE_MANAGE, False),
        # Clients are view-only on tasks (Section 5.3.B).
        (UserRole.CLIENT, Permission.TASK_VIEW, True),
        (UserRole.CLIENT, Permission.TASK_CREATE, False),
        (UserRole.CLIENT, Permission.TASK_UPDATE, False),
        (UserRole.CLIENT, Permission.TASK_COMPLETE, False),
        (UserRole.CLIENT, Permission.TASK_DELETE, False),
        (UserRole.CLIENT, Permission.CLIENT_ASSIGN_MANAGER, False),
        (UserRole.CLIENT, Permission.INVOICE_MANAGE, False),
        (UserRole.CLIENT, Permission.CONTENT_MANAGE, False),
        (UserRole.CLIENT, Permission.CHAT_LOGS_VIEW, False),
    ],
)
def test_role_permission_matrix(
    seeded_db: Session, make_user, role: UserRole, permission: Permission, expected: bool
) -> None:
    user, _ = make_user(role)
    assert has_permission(seeded_db, user, permission) is expected


def test_manager_cannot_delete_tasks_even_though_it_can_complete_them(
    seeded_db: Session, make_user
) -> None:
    """Section 6.2 calls this out specifically as a privilege-escalation risk."""
    manager, _ = make_user(UserRole.MANAGER)
    assert has_permission(seeded_db, manager, Permission.TASK_COMPLETE) is True
    assert has_permission(seeded_db, manager, Permission.TASK_DELETE) is False


def test_deactivated_user_holds_no_permissions(seeded_db: Session, make_user) -> None:
    admin, _ = make_user(UserRole.ADMIN, is_active=False)
    for permission in Permission:
        assert has_permission(seeded_db, admin, permission) is False


# --- Setting-gated rules (Section 13 items 5 and 6) --------------------------


def test_manager_content_access_follows_the_setting(seeded_db: Session, make_user) -> None:
    manager, _ = make_user(UserRole.MANAGER)

    assert has_permission(seeded_db, manager, Permission.CONTENT_MANAGE) is False
    assert has_permission(seeded_db, manager, Permission.FAQ_MANAGE) is False

    set_setting(seeded_db, SettingKey.MANAGER_CAN_MANAGE_CONTENT, True)

    assert has_permission(seeded_db, manager, Permission.CONTENT_MANAGE) is True
    assert has_permission(seeded_db, manager, Permission.FAQ_MANAGE) is True


def test_enabling_manager_content_does_not_grant_anything_else(
    seeded_db: Session, make_user
) -> None:
    """A setting must widen exactly one rule, not open the matrix."""
    manager, _ = make_user(UserRole.MANAGER)
    set_setting(seeded_db, SettingKey.MANAGER_CAN_MANAGE_CONTENT, True)

    assert has_permission(seeded_db, manager, Permission.TASK_DELETE) is False
    assert has_permission(seeded_db, manager, Permission.SETTINGS_MANAGE) is False
    assert has_permission(seeded_db, manager, Permission.CLIENT_ASSIGN_MANAGER) is False


# --- Enforcement over HTTP ---------------------------------------------------


def test_admin_only_endpoint_rejects_manager(api: TestClient, make_user, login) -> None:
    make_user(UserRole.MANAGER, email="mgr@example.com")
    headers = login("mgr@example.com")

    response = api.post("/api/v1/admin/invites", json={"email": "new@example.com"}, headers=headers)
    assert response.status_code == 403


def test_admin_only_endpoint_rejects_client(api: TestClient, make_user, login) -> None:
    make_user(UserRole.CLIENT, email="client@example.com")
    headers = login("client@example.com")

    response = api.get("/api/v1/admin/invites", headers=headers)
    assert response.status_code == 403


def test_admin_only_endpoint_rejects_anonymous(api: TestClient) -> None:
    assert api.get("/api/v1/admin/invites").status_code == 401


def test_admin_only_endpoint_allows_admin(api: TestClient, make_user, login) -> None:
    make_user(UserRole.ADMIN, email="admin@example.com")
    headers = login("admin@example.com")
    assert api.get("/api/v1/admin/invites", headers=headers).status_code == 200


# --- The /admin namespace is staff-only ------------------------------------------


def test_a_client_is_refused_everywhere_under_admin(api: TestClient, make_user, login) -> None:
    """Several permissions are shared between clients and staff — a client may
    view their own tasks, documents, invoices and notes. A permission check
    alone would therefore let them call the staff endpoint and receive the
    staff serialisation, which carries internal fields the portal withholds.

    The surface is read from the OpenAPI schema rather than a hand-written
    list, so an endpoint added later is covered without anyone remembering to
    extend this test. (app.routes is not usable here: this FastAPI version
    keeps included routers lazily rather than flattening them.)
    """
    make_user(UserRole.CLIENT, email="client@example.com")
    headers = login("client@example.com")

    paths = api.app.openapi()["paths"]
    checked = 0
    for path, operations in paths.items():
        if "/admin/" not in path:
            continue
        # Any path parameter will do; authorisation is refused before the value
        # is looked at.
        concrete = re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000000", path)
        for method in operations:
            response = api.request(method.upper(), concrete, json={}, headers=headers)
            assert response.status_code == 403, (
                f"{method.upper()} {concrete} returned {response.status_code}, expected 403"
            )
            checked += 1

    assert checked > 30, f"expected to cover the admin surface, only saw {checked}"


# --- What the caller is told they can do ------------------------------------------


def test_effective_permissions_agree_with_the_checks_the_endpoints_make(
    seeded_db: Session, make_user
) -> None:
    """The set handed to the frontend is derived from `has_permission` itself,
    so the navigation cannot come to disagree with what the API enforces."""
    for role in (UserRole.ADMIN, UserRole.MANAGER, UserRole.CLIENT):
        user, _ = make_user(role)
        granted = effective_permissions(seeded_db, user)
        for permission in Permission:
            assert (permission in granted) is has_permission(seeded_db, user, permission)


def test_me_tells_a_manager_what_they_may_do(api: TestClient, make_user, login) -> None:
    make_user(UserRole.MANAGER, email="mgr@example.com")
    body = api.get("/api/v1/auth/me", headers=login("mgr@example.com")).json()
    held = set(body["permissions"])

    assert Permission.TASK_COMPLETE in held
    assert Permission.CLIENT_VIEW in held
    # The sections a Manager must not be offered.
    assert Permission.SETTINGS_MANAGE not in held
    assert Permission.INVITE_MANAGE not in held
    assert Permission.TASK_DELETE not in held
    assert Permission.CONTENT_MANAGE not in held


def test_the_reported_set_follows_the_content_setting(
    api: TestClient, db: Session, make_user, login
) -> None:
    """Content access is a runtime setting, so a role-based list in the frontend
    would go stale the moment SmartAWARE switches it on."""
    make_user(UserRole.MANAGER, email="mgr@example.com")
    headers = login("mgr@example.com")

    before = api.get("/api/v1/auth/me", headers=headers).json()["permissions"]
    assert Permission.CONTENT_MANAGE not in before

    set_setting(db, SettingKey.MANAGER_CAN_MANAGE_CONTENT, True)
    db.flush()
    invalidate()

    after = api.get("/api/v1/auth/me", headers=headers).json()["permissions"]
    assert Permission.CONTENT_MANAGE in after


def test_an_admin_is_told_they_hold_everything(api: TestClient, make_user, login) -> None:
    make_user(UserRole.ADMIN, email="boss@example.com")
    body = api.get("/api/v1/auth/me", headers=login("boss@example.com")).json()
    assert set(body["permissions"]) == {p.value for p in Permission}
