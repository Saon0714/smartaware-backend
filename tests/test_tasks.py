"""Task workflow — spec Sections 5.3.B, 6.1, 6.2 and 6.3."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_service import invalidate
from app.models.audit import AuditLog
from app.models.enums import ClientStatus, UserRole
from app.models.task import Task
from app.services.notification.backends import console_backend


@pytest.fixture(autouse=True)
def _reset() -> None:
    invalidate()
    console_backend.clear()


@pytest.fixture
def admin_headers(api: TestClient, make_user, login) -> dict[str, str]:
    make_user(UserRole.ADMIN, email="admin@example.com")
    return login("admin@example.com")


@pytest.fixture
def setup(api: TestClient, make_user, login):
    """An admin, a manager, and a client assigned to that manager."""
    make_user(UserRole.ADMIN, email="admin@example.com")
    manager, _ = make_user(UserRole.MANAGER, email="mgr@example.com")
    user, client = make_user(
        UserRole.CLIENT,
        email="client@example.com",
        company_name="Acme Ltd",
        assigned_manager=manager,
    )
    return {
        "admin": login("admin@example.com"),
        "manager": login("mgr@example.com"),
        "client": login("client@example.com"),
        "manager_user": manager,
        "client_record": client,
        "client_user": user,
    }


def _create(api: TestClient, headers, client_id, **overrides) -> dict:
    body = {"client_id": str(client_id), "title": "Prepare annual accounts", **overrides}
    response = api.post("/api/v1/admin/tasks", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# --- The permission matrix (Section 6.1) -----------------------------------------


def test_manager_can_create_update_and_complete(api: TestClient, setup) -> None:
    task = _create(api, setup["manager"], setup["client_record"].id)

    updated = api.patch(
        f"/api/v1/admin/tasks/{task['id']}",
        json={"status": "in_progress", "description": "Draft prepared."},
        headers=setup["manager"],
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "in_progress"

    completed = api.post(
        f"/api/v1/admin/tasks/{task['id']}/complete",
        json={"note": "Accounts filed with Companies House."},
        headers=setup["manager"],
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"


def test_manager_cannot_delete(api: TestClient, setup) -> None:
    """Section 6.2 names this specifically as a privilege-escalation risk, so
    it is refused at the API rather than hidden in the UI."""
    task = _create(api, setup["manager"], setup["client_record"].id)
    response = api.delete(f"/api/v1/admin/tasks/{task['id']}", headers=setup["manager"])
    assert response.status_code == 403


def test_admin_can_delete(api: TestClient, setup) -> None:
    task = _create(api, setup["admin"], setup["client_record"].id)
    response = api.delete(f"/api/v1/admin/tasks/{task['id']}", headers=setup["admin"])
    assert response.status_code == 200
    assert response.json()["is_archived"] is True


def test_delete_archives_rather_than_destroys(api: TestClient, db: Session, setup) -> None:
    """A task is the record that work was done — losing it would remove
    evidence relevant to billing or a dispute."""
    task = _create(api, setup["admin"], setup["client_record"].id)
    api.delete(f"/api/v1/admin/tasks/{task['id']}", headers=setup["admin"])

    row = db.get(Task, task["id"])
    assert row is not None
    assert row.is_archived is True

    assert task["id"] not in [
        t["id"] for t in api.get("/api/v1/admin/tasks", headers=setup["admin"]).json()
    ]
    assert task["id"] in [
        t["id"]
        for t in api.get("/api/v1/admin/tasks?include_archived=true", headers=setup["admin"]).json()
    ]

    restored = api.post(f"/api/v1/admin/tasks/{task['id']}/restore", headers=setup["admin"])
    assert restored.json()["is_archived"] is False


# --- Clients are view-only (Section 5.3.B) ----------------------------------------


def test_client_can_read_their_own_tasks(api: TestClient, setup) -> None:
    _create(api, setup["admin"], setup["client_record"].id)
    rows = api.get("/api/v1/portal/tasks", headers=setup["client"]).json()
    assert [t["title"] for t in rows] == ["Prepare annual accounts"]


def test_client_cannot_reach_the_staff_task_endpoints(api: TestClient, setup) -> None:
    task = _create(api, setup["admin"], setup["client_record"].id)
    headers = setup["client"]

    assert api.get("/api/v1/admin/tasks", headers=headers).status_code == 403
    assert (
        api.post(
            "/api/v1/admin/tasks",
            json={"client_id": str(setup["client_record"].id), "title": "Mine now"},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        api.patch(
            f"/api/v1/admin/tasks/{task['id']}",
            json={"status": "in_progress"},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        api.post(
            f"/api/v1/admin/tasks/{task['id']}/complete",
            json={"note": "Done by me."},
            headers=headers,
        ).status_code
        == 403
    )
    assert api.delete(f"/api/v1/admin/tasks/{task['id']}", headers=headers).status_code == 403


def test_the_portal_task_surface_is_read_only(api: TestClient, setup) -> None:
    """Not merely forbidden — the write routes do not exist."""
    for method in ("POST", "PATCH", "PUT", "DELETE"):
        response = api.request(method, "/api/v1/portal/tasks", json={}, headers=setup["client"])
        assert response.status_code == 405, f"{method} should not exist"


def test_a_client_cannot_read_another_clients_task(
    api: TestClient, make_user, login, setup
) -> None:
    task = _create(api, setup["admin"], setup["client_record"].id)
    make_user(UserRole.CLIENT, email="other@example.com")

    other = login("other@example.com")
    assert api.get("/api/v1/portal/tasks", headers=other).json() == []
    assert api.get(f"/api/v1/portal/tasks/{task['id']}", headers=other).status_code == 404


def test_the_client_view_withholds_internal_detail(api: TestClient, setup) -> None:
    """Who inside SmartAWARE is doing the work is not the client's record."""
    _create(api, setup["admin"], setup["client_record"].id)
    row = api.get("/api/v1/portal/tasks", headers=setup["client"]).json()[0]

    assert "assigned_manager" not in row
    assert "created_by" not in row
    assert "is_archived" not in row


def test_an_archived_task_disappears_from_the_client_view(api: TestClient, setup) -> None:
    task = _create(api, setup["admin"], setup["client_record"].id)
    api.delete(f"/api/v1/admin/tasks/{task['id']}", headers=setup["admin"])

    assert api.get("/api/v1/portal/tasks", headers=setup["client"]).json() == []
    assert api.get(f"/api/v1/portal/tasks/{task['id']}", headers=setup["client"]).status_code == 404


# --- Completion (Section 6.3) ------------------------------------------------------


def test_completion_requires_a_note(api: TestClient, setup) -> None:
    task = _create(api, setup["manager"], setup["client_record"].id)
    response = api.post(
        f"/api/v1/admin/tasks/{task['id']}/complete",
        json={"note": ""},
        headers=setup["manager"],
    )
    assert response.status_code == 422


def test_completion_cannot_be_backdated(api: TestClient, db: Session, setup) -> None:
    """Section 6.3 recommends a server-side timestamp for exactly this reason,
    so the request has nowhere to put a date."""
    task = _create(api, setup["manager"], setup["client_record"].id)
    before = datetime.now(UTC)

    api.post(
        f"/api/v1/admin/tasks/{task['id']}/complete",
        json={"note": "Filed.", "completed_at": "2020-01-01T00:00:00Z"},
        headers=setup["manager"],
    )

    row = db.get(Task, task["id"])
    assert row.completed_at >= before


def test_status_cannot_be_set_to_completed_through_a_general_update(api: TestClient, setup) -> None:
    """Otherwise the note and the server timestamp could both be bypassed."""
    task = _create(api, setup["manager"], setup["client_record"].id)
    response = api.patch(
        f"/api/v1/admin/tasks/{task['id']}",
        json={"status": "completed"},
        headers=setup["manager"],
    )
    assert response.status_code == 400
    assert "completion note is required" in response.json()["detail"]


def test_completing_twice_is_refused(api: TestClient, setup) -> None:
    task = _create(api, setup["manager"], setup["client_record"].id)
    body = {"note": "Filed."}
    assert (
        api.post(
            f"/api/v1/admin/tasks/{task['id']}/complete", json=body, headers=setup["manager"]
        ).status_code
        == 200
    )
    assert (
        api.post(
            f"/api/v1/admin/tasks/{task['id']}/complete", json=body, headers=setup["manager"]
        ).status_code
        == 400
    )


def test_completion_notifies_the_client(api: TestClient, setup) -> None:
    task = _create(api, setup["manager"], setup["client_record"].id)
    api.post(
        f"/api/v1/admin/tasks/{task['id']}/complete",
        json={"note": "Accounts filed with Companies House."},
        headers=setup["manager"],
    )

    assert [m.to for m in console_backend.sent] == ["client@example.com"]
    message = console_backend.sent[0]
    assert "Prepare annual accounts" in message.subject
    assert "Accounts filed with Companies House." in message.body


def test_completion_is_audited(api: TestClient, db: Session, setup) -> None:
    task = _create(api, setup["manager"], setup["client_record"].id)
    api.post(
        f"/api/v1/admin/tasks/{task['id']}/complete",
        json={"note": "Filed on time."},
        headers=setup["manager"],
    )

    entry = db.execute(
        select(AuditLog).where(AuditLog.entity_type == "task", AuditLog.action == "task.completed")
    ).scalar_one()
    assert entry.reason == "Filed on time."
    assert entry.actor_id == setup["manager_user"].id


def test_a_completed_task_is_locked_until_reopened(api: TestClient, setup) -> None:
    task = _create(api, setup["manager"], setup["client_record"].id)
    api.post(
        f"/api/v1/admin/tasks/{task['id']}/complete",
        json={"note": "Filed."},
        headers=setup["manager"],
    )

    blocked = api.patch(
        f"/api/v1/admin/tasks/{task['id']}",
        json={"description": "Actually, more to do."},
        headers=setup["manager"],
    )
    assert blocked.status_code == 400

    reopened = api.post(f"/api/v1/admin/tasks/{task['id']}/reopen", headers=setup["manager"])
    assert reopened.status_code == 200
    assert reopened.json()["completed_at"] is None
    assert reopened.json()["completed_note"] is None

    assert (
        api.patch(
            f"/api/v1/admin/tasks/{task['id']}",
            json={"description": "More to do."},
            headers=setup["manager"],
        ).status_code
        == 200
    )


# --- Hold blocks work (Section 6.2) -------------------------------------------------


def test_no_work_is_recorded_for_a_client_on_hold(api: TestClient, db: Session, setup) -> None:
    task = _create(api, setup["manager"], setup["client_record"].id)

    setup["client_record"].status = ClientStatus.HOLD
    db.flush()

    created = api.post(
        "/api/v1/admin/tasks",
        json={"client_id": str(setup["client_record"].id), "title": "New work"},
        headers=setup["manager"],
    )
    assert created.status_code == 400
    assert "on hold" in created.json()["detail"]

    completed = api.post(
        f"/api/v1/admin/tasks/{task['id']}/complete",
        json={"note": "Trying anyway."},
        headers=setup["manager"],
    )
    assert completed.status_code == 400

    updated = api.patch(
        f"/api/v1/admin/tasks/{task['id']}",
        json={"status": "in_progress"},
        headers=setup["manager"],
    )
    assert updated.status_code == 400


def test_work_resumes_once_the_account_is_active_again(api: TestClient, db: Session, setup) -> None:
    setup["client_record"].status = ClientStatus.HOLD
    db.flush()
    assert (
        api.post(
            "/api/v1/admin/tasks",
            json={"client_id": str(setup["client_record"].id), "title": "Blocked"},
            headers=setup["manager"],
        ).status_code
        == 400
    )

    setup["client_record"].status = ClientStatus.ACTIVE
    db.flush()
    assert (
        api.post(
            "/api/v1/admin/tasks",
            json={"client_id": str(setup["client_record"].id), "title": "Allowed"},
            headers=setup["manager"],
        ).status_code
        == 201
    )


# --- Scoping --------------------------------------------------------------------


def test_a_manager_sees_only_their_clients_tasks(api: TestClient, make_user, login, setup) -> None:
    _create(api, setup["admin"], setup["client_record"].id)

    other_manager, _ = make_user(UserRole.MANAGER, email="other@example.com")
    _user, other_client = make_user(UserRole.CLIENT, assigned_manager=other_manager)
    _create(api, setup["admin"], other_client.id, title="Someone else's work")

    mine = api.get("/api/v1/admin/tasks", headers=setup["manager"]).json()
    assert [t["title"] for t in mine] == ["Prepare annual accounts"]

    assert len(api.get("/api/v1/admin/tasks", headers=setup["admin"]).json()) == 2


def test_a_manager_cannot_create_work_for_a_client_they_do_not_hold(
    api: TestClient, make_user, setup
) -> None:
    _user, other_client = make_user(UserRole.CLIENT)
    response = api.post(
        "/api/v1/admin/tasks",
        json={"client_id": str(other_client.id), "title": "Not mine"},
        headers=setup["manager"],
    )
    assert response.status_code == 404


def test_tasks_can_only_be_assigned_to_active_staff(api: TestClient, make_user, setup) -> None:
    inactive, _ = make_user(UserRole.MANAGER, is_active=False)
    client_user, _ = make_user(UserRole.CLIENT, email="notstaff@example.com")

    for bad_id in (inactive.id, client_user.id):
        response = api.post(
            "/api/v1/admin/tasks",
            json={
                "client_id": str(setup["client_record"].id),
                "title": "Assignment check",
                "assigned_manager_id": str(bad_id),
            },
            headers=setup["admin"],
        )
        assert response.status_code == 400


# --- Counts and overdue -------------------------------------------------------------


def test_counts_reflect_status_and_overdue(api: TestClient, setup) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    _create(api, setup["admin"], setup["client_record"].id, title="Overdue one", due_date=yesterday)
    done = _create(api, setup["admin"], setup["client_record"].id, title="Finished")
    api.post(
        f"/api/v1/admin/tasks/{done['id']}/complete",
        json={"note": "Filed."},
        headers=setup["admin"],
    )

    counts = api.get("/api/v1/admin/tasks/counts", headers=setup["admin"]).json()
    assert counts["total"] == 2
    assert counts["completed"] == 1
    assert counts["overdue"] == 1

    mine = api.get("/api/v1/portal/tasks/counts", headers=setup["client"]).json()
    assert mine["total"] == 2


def test_a_completed_task_is_never_overdue(api: TestClient, setup) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    task = _create(api, setup["admin"], setup["client_record"].id, due_date=yesterday)
    api.post(
        f"/api/v1/admin/tasks/{task['id']}/complete",
        json={"note": "Late, but done."},
        headers=setup["admin"],
    )
    counts = api.get("/api/v1/admin/tasks/counts", headers=setup["admin"]).json()
    assert counts["overdue"] == 0
