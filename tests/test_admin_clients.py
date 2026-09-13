"""Client account management — spec Section 6.2.

Client isolation is exercised here as well as in test_client_isolation, because
this is the first surface where a Manager can actually reach client records
over HTTP.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_service import SettingKey, invalidate, set_setting
from app.models.audit import AuditLog
from app.models.enums import ClientStatus, UserRole
from app.services import client_service
from app.services.client_service import ClientError


@pytest.fixture(autouse=True)
def _reset() -> None:
    invalidate()


@pytest.fixture
def admin_headers(api: TestClient, make_user, login) -> dict[str, str]:
    make_user(UserRole.ADMIN, email="admin@example.com")
    return login("admin@example.com")


# --- Listing and scoping ---------------------------------------------------------


def test_admin_sees_every_client_with_their_manager(
    api: TestClient, make_user, admin_headers
) -> None:
    manager, _ = make_user(UserRole.MANAGER, email="mgr@example.com")
    make_user(UserRole.CLIENT, company_name="Assigned Co", assigned_manager=manager)
    make_user(UserRole.CLIENT, company_name="Unassigned Co")

    rows = api.get("/api/v1/admin/clients", headers=admin_headers).json()
    by_company = {r["company_name"]: r for r in rows}

    assert set(by_company) == {"Assigned Co", "Unassigned Co"}
    assert by_company["Assigned Co"]["assigned_manager"]["email"] == "mgr@example.com"
    assert by_company["Unassigned Co"]["assigned_manager"] is None


def test_manager_sees_only_their_own_clients(api: TestClient, make_user, login) -> None:
    manager, _ = make_user(UserRole.MANAGER, email="mine@example.com")
    other, _ = make_user(UserRole.MANAGER, email="theirs@example.com")
    make_user(UserRole.CLIENT, company_name="Mine", assigned_manager=manager)
    make_user(UserRole.CLIENT, company_name="Theirs", assigned_manager=other)
    make_user(UserRole.CLIENT, company_name="Nobody's")

    rows = api.get("/api/v1/admin/clients", headers=login("mine@example.com")).json()
    assert [r["company_name"] for r in rows] == ["Mine"]


def test_manager_scope_widens_when_the_setting_says_all(
    api: TestClient, db: Session, make_user, login
) -> None:
    manager, _ = make_user(UserRole.MANAGER, email="mgr@example.com")
    make_user(UserRole.CLIENT, company_name="Someone Else's")

    headers = login("mgr@example.com")
    assert api.get("/api/v1/admin/clients", headers=headers).json() == []

    set_setting(db, SettingKey.MANAGER_CLIENT_SCOPE, "all")
    rows = api.get("/api/v1/admin/clients", headers=headers).json()
    assert [r["company_name"] for r in rows] == ["Someone Else's"]


def test_a_client_outside_scope_reads_as_missing_not_forbidden(
    api: TestClient, make_user, login
) -> None:
    """403 would confirm the account exists, which leaks the client list."""
    make_user(UserRole.MANAGER, email="mgr@example.com")
    _user, other = make_user(UserRole.CLIENT, company_name="Not Theirs")

    response = api.get(f"/api/v1/admin/clients/{other.id}", headers=login("mgr@example.com"))
    assert response.status_code == 404


def test_a_client_cannot_use_the_admin_client_list(api: TestClient, make_user, login) -> None:
    make_user(UserRole.CLIENT, email="client@example.com")
    assert api.get("/api/v1/admin/clients", headers=login("client@example.com")).status_code == 403


def test_filters_narrow_the_list(api: TestClient, make_user, admin_headers) -> None:
    manager, _ = make_user(UserRole.MANAGER, email="mgr@example.com")
    make_user(
        UserRole.CLIENT,
        company_name="Held Co",
        client_status=ClientStatus.HOLD,
        assigned_manager=manager,
    )
    make_user(UserRole.CLIENT, company_name="Active Co")

    held = api.get("/api/v1/admin/clients?status=hold", headers=admin_headers).json()
    assert [r["company_name"] for r in held] == ["Held Co"]

    unassigned = api.get("/api/v1/admin/clients?unassigned=true", headers=admin_headers).json()
    assert [r["company_name"] for r in unassigned] == ["Active Co"]

    found = api.get("/api/v1/admin/clients?search=Held", headers=admin_headers).json()
    assert [r["company_name"] for r in found] == ["Held Co"]


# --- Status (Section 6.2) ---------------------------------------------------------


def test_admin_can_place_an_account_on_hold(api: TestClient, make_user, admin_headers) -> None:
    _user, client = make_user(UserRole.CLIENT, company_name="Acme")

    response = api.post(
        f"/api/v1/admin/clients/{client.id}/status",
        json={"status": "hold", "note": "Client pausing until the new tax year."},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "hold"
    assert response.json()["status_note"].startswith("Client pausing")


def test_a_status_change_requires_a_reason(api: TestClient, make_user, admin_headers) -> None:
    """Otherwise nobody can later tell a pause from a termination."""
    _user, client = make_user(UserRole.CLIENT)
    response = api.post(
        f"/api/v1/admin/clients/{client.id}/status",
        json={"status": "hold", "note": ""},
        headers=admin_headers,
    )
    assert response.status_code == 422


def test_putting_a_client_on_hold_ends_their_session_immediately(
    api: TestClient, make_user, login, admin_headers
) -> None:
    make_user(UserRole.CLIENT, email="client@example.com")
    client_headers = login("client@example.com")
    assert api.get("/api/v1/auth/me", headers=client_headers).status_code == 200

    rows = api.get("/api/v1/admin/clients", headers=admin_headers).json()
    api.post(
        f"/api/v1/admin/clients/{rows[0]['id']}/status",
        json={"status": "hold", "note": "Paused at the client's request."},
        headers=admin_headers,
    )

    assert api.get("/api/v1/auth/me", headers=client_headers).status_code == 403
    assert (
        api.post(
            "/api/v1/auth/login",
            json={"email": "client@example.com", "password": "correct horse battery staple"},
        ).status_code
        == 403
    )


def test_a_manager_cannot_change_status(api: TestClient, make_user, login) -> None:
    """Section 6.2 places this with Admin alone."""
    manager, _ = make_user(UserRole.MANAGER, email="mgr@example.com")
    _user, client = make_user(UserRole.CLIENT, assigned_manager=manager)

    response = api.post(
        f"/api/v1/admin/clients/{client.id}/status",
        json={"status": "hold", "note": "Trying it on."},
        headers=login("mgr@example.com"),
    )
    assert response.status_code == 403


def test_reactivating_restores_access(api: TestClient, make_user, login, admin_headers) -> None:
    make_user(UserRole.CLIENT, email="client@example.com", client_status=ClientStatus.HOLD)
    rows = api.get("/api/v1/admin/clients", headers=admin_headers).json()

    api.post(
        f"/api/v1/admin/clients/{rows[0]['id']}/status",
        json={"status": "active", "note": "Client resuming."},
        headers=admin_headers,
    )
    assert (
        api.post(
            "/api/v1/auth/login",
            json={"email": "client@example.com", "password": "correct horse battery staple"},
        ).status_code
        == 200
    )


def test_hold_and_deactive_both_block_work(seeded_db: Session, make_user) -> None:
    """Section 6.2: while on hold the manager performs no work. Enforced here
    so the task endpoints in the next chunk cannot be called around it."""
    _u1, active = make_user(UserRole.CLIENT)
    _u2, held = make_user(UserRole.CLIENT, client_status=ClientStatus.HOLD)
    _u3, gone = make_user(UserRole.CLIENT, client_status=ClientStatus.DEACTIVE)

    client_service.assert_work_permitted(seeded_db, active.id)

    with pytest.raises(ClientError, match="on hold"):
        client_service.assert_work_permitted(seeded_db, held.id)
    with pytest.raises(ClientError, match="deactivated"):
        client_service.assert_work_permitted(seeded_db, gone.id)


# --- Manager assignment -----------------------------------------------------------


def test_admin_assigns_and_reassigns_a_manager(api: TestClient, make_user, admin_headers) -> None:
    first, _ = make_user(UserRole.MANAGER, email="first@example.com")
    second, _ = make_user(UserRole.MANAGER, email="second@example.com")
    _user, client = make_user(UserRole.CLIENT)

    assigned = api.post(
        f"/api/v1/admin/clients/{client.id}/manager",
        json={"manager_id": str(first.id)},
        headers=admin_headers,
    )
    assert assigned.json()["assigned_manager"]["email"] == "first@example.com"

    reassigned = api.post(
        f"/api/v1/admin/clients/{client.id}/manager",
        json={"manager_id": str(second.id)},
        headers=admin_headers,
    )
    assert reassigned.json()["assigned_manager"]["email"] == "second@example.com"


def test_reassignment_moves_visibility_at_once(
    api: TestClient, make_user, login, admin_headers
) -> None:
    first, _ = make_user(UserRole.MANAGER, email="first@example.com")
    second, _ = make_user(UserRole.MANAGER, email="second@example.com")
    _user, client = make_user(UserRole.CLIENT, company_name="Moving Co", assigned_manager=first)

    assert len(api.get("/api/v1/admin/clients", headers=login("first@example.com")).json()) == 1
    assert api.get("/api/v1/admin/clients", headers=login("second@example.com")).json() == []

    api.post(
        f"/api/v1/admin/clients/{client.id}/manager",
        json={"manager_id": str(second.id)},
        headers=admin_headers,
    )

    assert api.get("/api/v1/admin/clients", headers=login("first@example.com")).json() == []
    assert len(api.get("/api/v1/admin/clients", headers=login("second@example.com")).json()) == 1


def test_assignment_can_be_cleared(api: TestClient, make_user, admin_headers) -> None:
    manager, _ = make_user(UserRole.MANAGER)
    _user, client = make_user(UserRole.CLIENT, assigned_manager=manager)

    response = api.post(
        f"/api/v1/admin/clients/{client.id}/manager",
        json={"manager_id": None},
        headers=admin_headers,
    )
    assert response.json()["assigned_manager"] is None


def test_only_an_active_manager_can_be_assigned(api: TestClient, make_user, admin_headers) -> None:
    client_user, _ = make_user(UserRole.CLIENT, email="notamanager@example.com")
    inactive, _ = make_user(UserRole.MANAGER, is_active=False)
    _user, client = make_user(UserRole.CLIENT)

    not_a_manager = api.post(
        f"/api/v1/admin/clients/{client.id}/manager",
        json={"manager_id": str(client_user.id)},
        headers=admin_headers,
    )
    assert not_a_manager.status_code == 400

    deactivated = api.post(
        f"/api/v1/admin/clients/{client.id}/manager",
        json={"manager_id": str(inactive.id)},
        headers=admin_headers,
    )
    assert deactivated.status_code == 400


def test_a_manager_cannot_reassign_their_own_clients(api: TestClient, make_user, login) -> None:
    manager, _ = make_user(UserRole.MANAGER, email="mgr@example.com")
    other, _ = make_user(UserRole.MANAGER)
    _user, client = make_user(UserRole.CLIENT, assigned_manager=manager)

    response = api.post(
        f"/api/v1/admin/clients/{client.id}/manager",
        json={"manager_id": str(other.id)},
        headers=login("mgr@example.com"),
    )
    assert response.status_code == 403


def test_staff_list_offers_only_active_managers(api: TestClient, make_user, admin_headers) -> None:
    make_user(UserRole.MANAGER, email="active@example.com")
    make_user(UserRole.MANAGER, email="inactive@example.com", is_active=False)

    emails = [
        s["email"]
        for s in api.get("/api/v1/admin/staff?managers_only=true", headers=admin_headers).json()
    ]
    assert "active@example.com" in emails
    assert "inactive@example.com" not in emails


# --- Audit (Section 9) ------------------------------------------------------------


def test_status_and_reassignment_are_audited(
    api: TestClient, db: Session, make_user, admin_headers
) -> None:
    manager, _ = make_user(UserRole.MANAGER, email="mgr@example.com")
    _user, client = make_user(UserRole.CLIENT)

    api.post(
        f"/api/v1/admin/clients/{client.id}/manager",
        json={"manager_id": str(manager.id)},
        headers=admin_headers,
    )
    api.post(
        f"/api/v1/admin/clients/{client.id}/status",
        json={"status": "hold", "note": "Awaiting documents."},
        headers=admin_headers,
    )

    entries = api.get(f"/api/v1/admin/clients/{client.id}/audit", headers=admin_headers).json()
    actions = [e["action"] for e in entries]
    assert "client.manager_assigned" in actions
    assert "client.status_changed" in actions

    status_entry = next(e for e in entries if e["action"] == "client.status_changed")
    assert status_entry["old_value"]["status"] == "active"
    assert status_entry["new_value"]["status"] == "hold"
    assert status_entry["reason"] == "Awaiting documents."
    assert status_entry["actor_email"] == "admin@example.com"


def test_a_refused_change_leaves_no_audit_entry(
    api: TestClient, db: Session, make_user, admin_headers
) -> None:
    """The record and the change share a transaction."""
    _user, client = make_user(UserRole.CLIENT)

    refused = api.post(
        f"/api/v1/admin/clients/{client.id}/status",
        json={"status": "active", "note": "Already active."},
        headers=admin_headers,
    )
    assert refused.status_code == 400

    assert db.execute(select(AuditLog).where(AuditLog.entity_id == client.id)).first() is None
