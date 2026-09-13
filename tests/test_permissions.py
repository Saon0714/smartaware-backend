"""The Section 6.1 permission matrix, enforced server-side.

Spec Section 9 requires role checks at the API layer and treats UI hiding as
insufficient. These tests therefore assert on the matrix itself and, where a
rule is easy to get wrong, on the HTTP response.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.permissions import Permission, has_permission
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
