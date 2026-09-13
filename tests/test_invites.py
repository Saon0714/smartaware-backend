"""Invite-only sign-up — spec Section 5.1.

Single-use, expiring, and the only route to an account: there is no public
sign-up endpoint.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_token
from app.core.settings_service import SettingKey, invalidate, set_setting
from app.models.enums import ClientStatus, InviteStatus, UserRole
from app.models.user import Invite, User

NEW_PASSWORD = "a sufficiently long passphrase"


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    invalidate()


def _invite(api: TestClient, headers: dict[str, str], email: str, **kwargs) -> dict:
    response = api.post("/api/v1/admin/invites", json={"email": email, **kwargs}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def admin_headers(api: TestClient, make_user, login) -> dict[str, str]:
    make_user(UserRole.ADMIN, email="admin@example.com")
    return login("admin@example.com")


def _token_from(invite_url: str) -> str:
    return invite_url.rstrip("/").split("/")[-1]


# --- Issuing ------------------------------------------------------------------


def test_admin_can_issue_an_invite(api: TestClient, admin_headers) -> None:
    body = _invite(api, admin_headers, "new@example.com")
    assert body["invite"]["status"] == "pending"
    assert body["invite_url"]


def test_raw_token_is_never_stored(api: TestClient, db: Session, admin_headers) -> None:
    """Only a hash is persisted, so a database disclosure cannot be replayed."""
    body = _invite(api, admin_headers, "new@example.com")
    token = _token_from(body["invite_url"])

    invite = db.execute(select(Invite).where(Invite.email == "new@example.com")).scalar_one()
    assert invite.token_hash != token
    assert invite.token_hash == hash_token(token)


def test_cannot_invite_an_existing_account(api: TestClient, make_user, admin_headers) -> None:
    make_user(UserRole.CLIENT, email="taken@example.com")
    response = api.post(
        "/api/v1/admin/invites", json={"email": "taken@example.com"}, headers=admin_headers
    )
    assert response.status_code == 400


def test_second_admin_invite_blocked_while_setting_is_false(
    api: TestClient, db: Session, admin_headers
) -> None:
    """Section 13 item 4 — defaulted to a single primary Admin."""
    response = api.post(
        "/api/v1/admin/invites",
        json={"email": "admin2@example.com", "role": "admin"},
        headers=admin_headers,
    )
    assert response.status_code == 400

    set_setting(db, SettingKey.ALLOW_MULTIPLE_ADMINS, True)

    allowed = api.post(
        "/api/v1/admin/invites",
        json={"email": "admin2@example.com", "role": "admin"},
        headers=admin_headers,
    )
    assert allowed.status_code == 201


# --- Redeeming ----------------------------------------------------------------


def test_invite_can_be_checked_before_signing_up(api: TestClient, admin_headers) -> None:
    body = _invite(api, admin_headers, "new@example.com", company_name="Acme Ltd")
    token = _token_from(body["invite_url"])

    response = api.get(f"/api/v1/auth/invite/{token}")
    assert response.status_code == 200
    assert response.json()["email"] == "new@example.com"
    assert response.json()["company_name"] == "Acme Ltd"


def test_accepting_creates_a_user_and_client_profile(
    api: TestClient, db: Session, admin_headers
) -> None:
    body = _invite(api, admin_headers, "new@example.com", company_name="Acme Ltd")
    token = _token_from(body["invite_url"])

    response = api.post(
        f"/api/v1/auth/invite/{token}/accept",
        json={"password": NEW_PASSWORD, "full_name": "New Client"},
    )
    assert response.status_code == 201
    assert response.json()["user"]["role"] == "client"

    user = db.execute(select(User).where(User.email == "new@example.com")).scalar_one()
    assert user.client is not None
    assert user.client.company_name == "Acme Ltd"
    assert user.client.status is ClientStatus.ACTIVE
    assert user.client.client_ref.startswith("SA-")


def test_invite_is_single_use(api: TestClient, admin_headers) -> None:
    body = _invite(api, admin_headers, "new@example.com")
    token = _token_from(body["invite_url"])

    first = api.post(f"/api/v1/auth/invite/{token}/accept", json={"password": NEW_PASSWORD})
    assert first.status_code == 201

    second = api.post(f"/api/v1/auth/invite/{token}/accept", json={"password": NEW_PASSWORD})
    assert second.status_code == 400
    assert "already been used" in second.json()["detail"]


def test_expired_invite_is_rejected_with_a_clear_reason(
    api: TestClient, db: Session, admin_headers
) -> None:
    body = _invite(api, admin_headers, "new@example.com")
    token = _token_from(body["invite_url"])

    invite = db.execute(select(Invite).where(Invite.email == "new@example.com")).scalar_one()
    invite.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.flush()

    response = api.get(f"/api/v1/auth/invite/{token}")
    assert response.status_code == 400
    assert "expired" in response.json()["detail"].lower()


def test_expiry_window_follows_the_setting(api: TestClient, db: Session, admin_headers) -> None:
    """Spec 5.1 defaults to three days but requires it to be configurable."""
    set_setting(db, SettingKey.INVITE_EXPIRY_DAYS, 10)
    body = _invite(api, admin_headers, "new@example.com")

    expires = datetime.fromisoformat(body["invite"]["expires_at"])
    days = (expires - datetime.now(UTC)).days
    assert 9 <= days <= 10


def test_revoked_invite_cannot_be_redeemed(api: TestClient, admin_headers) -> None:
    body = _invite(api, admin_headers, "new@example.com")
    token = _token_from(body["invite_url"])

    api.post(f"/api/v1/admin/invites/{body['invite']['id']}/revoke", headers=admin_headers)

    response = api.get(f"/api/v1/auth/invite/{token}")
    assert response.status_code == 400
    assert "cancelled" in response.json()["detail"].lower()


def test_unknown_token_is_rejected(api: TestClient) -> None:
    assert api.get("/api/v1/auth/invite/not-a-real-token").status_code == 400


def test_resending_invalidates_the_previous_link(api: TestClient, admin_headers) -> None:
    """Otherwise every resend would leave another working link in the wild."""
    first = _invite(api, admin_headers, "new@example.com")
    old_token = _token_from(first["invite_url"])

    resend = api.post(
        f"/api/v1/admin/invites/{first['invite']['id']}/resend", headers=admin_headers
    )
    assert resend.status_code == 200
    new_token = _token_from(resend.json()["invite_url"])

    assert api.get(f"/api/v1/auth/invite/{old_token}").status_code == 400
    assert api.get(f"/api/v1/auth/invite/{new_token}").status_code == 200


def test_new_account_can_immediately_sign_in(api: TestClient, admin_headers) -> None:
    body = _invite(api, admin_headers, "new@example.com")
    token = _token_from(body["invite_url"])
    api.post(f"/api/v1/auth/invite/{token}/accept", json={"password": NEW_PASSWORD})
    api.post("/api/v1/auth/logout")

    response = api.post(
        "/api/v1/auth/login", json={"email": "new@example.com", "password": NEW_PASSWORD}
    )
    assert response.status_code == 200


def test_listing_reports_derived_expiry_status(api: TestClient, db: Session, admin_headers) -> None:
    _invite(api, admin_headers, "new@example.com")
    invite = db.execute(select(Invite).where(Invite.email == "new@example.com")).scalar_one()
    invite.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.flush()

    rows = api.get("/api/v1/admin/invites", headers=admin_headers).json()
    match = next(r for r in rows if r["email"] == "new@example.com")
    assert match["status"] == InviteStatus.EXPIRED.value


# --- Preselected services (the client has no say in what they are engaged for) -----


def _service_ids(db: Session, *names: str) -> list[str]:
    from app.models.service import ServiceCategory

    rows = db.execute(
        select(ServiceCategory).where(ServiceCategory.name.in_(names))
    ).scalars()
    by_name = {c.name: str(c.id) for c in rows}
    return [by_name[name] for name in names]


def test_services_chosen_at_invitation_land_on_the_new_client(
    api: TestClient, db: Session, admin_headers
) -> None:
    wanted = _service_ids(db, "Payroll", "VAT Services")
    body = _invite(
        api, admin_headers, "new@example.com", company_name="Acme Ltd", service_ids=wanted
    )
    assert sorted(s["name"] for s in body["invite"]["services"]) == ["Payroll", "VAT Services"]

    token = _token_from(body["invite_url"])
    api.post(f"/api/v1/auth/invite/{token}/accept", json={"password": NEW_PASSWORD})

    user = db.execute(select(User).where(User.email == "new@example.com")).scalar_one()
    assert sorted(s.name for s in user.client.services) == ["Payroll", "VAT Services"]


def test_the_invitee_is_shown_the_services_before_signing_up(
    api: TestClient, db: Session, admin_headers
) -> None:
    wanted = _service_ids(db, "Bookkeeping")
    body = _invite(api, admin_headers, "new@example.com", service_ids=wanted)
    token = _token_from(body["invite_url"])

    check = api.get(f"/api/v1/auth/invite/{token}").json()
    assert [s["name"] for s in check["services"]] == ["Bookkeeping"]


def test_the_person_signing_up_cannot_choose_their_own_services(
    api: TestClient, db: Session, admin_headers
) -> None:
    """The accept request has no services field, and adding one changes nothing.

    This is the whole point of holding the choice on the invitation: it is
    SmartAWARE's commercial decision, taken before the account exists.
    """
    wanted = _service_ids(db, "Bookkeeping")
    everything = _service_ids(db, "Payroll", "VAT Services", "Personal Tax")
    body = _invite(api, admin_headers, "new@example.com", service_ids=wanted)
    token = _token_from(body["invite_url"])

    response = api.post(
        f"/api/v1/auth/invite/{token}/accept",
        json={"password": NEW_PASSWORD, "service_ids": everything, "services": everything},
    )
    assert response.status_code == 201

    user = db.execute(select(User).where(User.email == "new@example.com")).scalar_one()
    assert [s.name for s in user.client.services] == ["Bookkeeping"]


def test_a_client_cannot_change_their_services_through_the_profile_form(
    api: TestClient, db: Session, make_user, login
) -> None:
    """The profile form writes to an allowlist of columns; anything else lands
    in `extra`. A field called `services` therefore cannot reach the
    relationship, whatever an editor names it in the Admin Portal."""
    from app.models.service import ServiceCategory

    user, client = make_user(UserRole.CLIENT, email="them@example.com")
    client.services = list(
        db.execute(select(ServiceCategory).where(ServiceCategory.name == "Payroll")).scalars()
    )
    db.flush()

    headers = login("them@example.com")
    response = api.patch(
        "/api/v1/portal/profile",
        json={"values": {"services": ["Personal Tax"], "service_ids": ["x"]}},
        headers=headers,
    )
    # Accepted, because the form silently ignores keys it does not define —
    # which is exactly why the allowlist matters. Nothing reached the services.
    assert response.status_code == 200

    db.refresh(client)
    assert [s.name for s in client.services] == ["Payroll"]


def test_resending_keeps_the_same_services(
    api: TestClient, db: Session, admin_headers
) -> None:
    """A fresh link has to stand for the same offer as the one it replaces."""
    wanted = _service_ids(db, "Payroll", "CIS Services")
    body = _invite(api, admin_headers, "new@example.com", service_ids=wanted)

    resent = api.post(
        f"/api/v1/admin/invites/{body['invite']['id']}/resend", headers=admin_headers
    ).json()
    assert sorted(s["name"] for s in resent["invite"]["services"]) == [
        "CIS Services",
        "Payroll",
    ]

    token = _token_from(resent["invite_url"])
    api.post(f"/api/v1/auth/invite/{token}/accept", json={"password": NEW_PASSWORD})
    user = db.execute(select(User).where(User.email == "new@example.com")).scalar_one()
    assert sorted(s.name for s in user.client.services) == ["CIS Services", "Payroll"]


def test_an_unknown_service_is_refused(api: TestClient, admin_headers) -> None:
    response = api.post(
        "/api/v1/admin/invites",
        json={
            "email": "new@example.com",
            "service_ids": ["00000000-0000-0000-0000-000000000001"],
        },
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "Unknown service" in response.json()["detail"]


def test_an_archived_service_cannot_be_sold_to_a_new_client(
    api: TestClient, db: Session, admin_headers
) -> None:
    """Unlike editing an existing client, who may still be engaged for
    something SmartAWARE has since withdrawn."""
    from app.models.service import ServiceCategory

    category = db.execute(
        select(ServiceCategory).where(ServiceCategory.name == "Payroll")
    ).scalar_one()
    category.is_archived = True
    db.flush()

    response = api.post(
        "/api/v1/admin/invites",
        json={"email": "new@example.com", "service_ids": [str(category.id)]},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "no longer offered" in response.json()["detail"]


def test_staff_invitations_cannot_carry_services(
    api: TestClient, db: Session, admin_headers
) -> None:
    """Only a client has services. Storing them on a manager invite would record
    a choice that redemption silently discards."""
    response = api.post(
        "/api/v1/admin/invites",
        json={
            "email": "mgr@example.com",
            "role": "manager",
            "service_ids": _service_ids(db, "Payroll"),
        },
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "client invitations" in response.json()["detail"]


# --- Manager accounts (Section 6.1) -----------------------------------------------


def test_admin_can_invite_a_manager_who_then_works_their_own_clients(
    api: TestClient, db: Session, make_user, admin_headers, login
) -> None:
    """The whole path the Admin Portal drives: invite, accept, tag, work.

    Asserted end to end because each step is only useful if the next follows —
    a manager account that signs in but sees nothing is no use.
    """
    body = _invite(api, admin_headers, "mgr@example.com", role="manager")
    assert body["invite"]["role"] == "manager"

    token = _token_from(body["invite_url"])
    session = api.post(
        f"/api/v1/auth/invite/{token}/accept",
        json={"password": NEW_PASSWORD, "full_name": "New Manager"},
    )
    assert session.status_code == 201
    assert session.json()["user"]["role"] == "manager"

    manager = db.execute(select(User).where(User.email == "mgr@example.com")).scalar_one()
    assert manager.client is None, "a manager has no client profile"

    # Signs in with the password they just chose, not the fixture default.
    headers = login("mgr@example.com", NEW_PASSWORD)
    # Nothing yet: an untagged manager sees an empty book, not everybody's.
    assert api.get("/api/v1/admin/clients", headers=headers).json() == []

    _user, client = make_user(UserRole.CLIENT, company_name="Tagged Ltd")
    make_user(UserRole.CLIENT, company_name="Someone Else Ltd")

    api.put(
        f"/api/v1/admin/staff/{manager.id}/clients",
        json={"client_ids": [str(client.id)]},
        headers=admin_headers,
    )

    seen = api.get("/api/v1/admin/clients", headers=headers).json()
    assert [r["company_name"] for r in seen] == ["Tagged Ltd"]

    # And can do the work Section 6.3 gives them.
    created = api.post(
        "/api/v1/admin/tasks",
        json={"client_id": str(client.id), "title": "Prepare year-end accounts"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]

    done = api.post(
        f"/api/v1/admin/tasks/{task_id}/complete",
        json={"note": "Filed and acknowledged."},
        headers=headers,
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"

    # But not the one thing Section 6.1 withholds.
    assert api.delete(f"/api/v1/admin/tasks/{task_id}", headers=headers).status_code == 403


def test_a_manager_is_not_told_they_are_getting_a_client_portal_account(
    api: TestClient, db: Session, admin_headers, monkeypatch
) -> None:
    """The same invitation creates staff accounts, so the email cannot hardcode
    "Client Portal" — that is a new Manager's first contact with the system."""
    from app.services.notification import service as notification_service

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        notification_service,
        "dispatch",
        lambda message: sent.append((message.subject, message.body)) or [],
    )

    _invite(api, admin_headers, "mgr@example.com", role="manager")
    _invite(api, admin_headers, "client@example.com")

    staff_subject, staff_body = sent[0]
    assert "Staff Portal" in staff_subject and "Staff Portal" in staff_body
    assert "Client Portal" not in staff_body

    client_subject, client_body = sent[1]
    assert "Client Portal" in client_subject and "Client Portal" in client_body


def test_a_manager_invitation_carries_no_company_or_services(
    api: TestClient, db: Session, admin_headers
) -> None:
    body = _invite(api, admin_headers, "mgr@example.com", role="manager")
    assert body["invite"]["prefill_company_name"] is None
    assert body["invite"]["services"] == []


def test_a_manager_cannot_send_invitations(api: TestClient, make_user, login) -> None:
    """Section 6.2 puts the invite system in Admin's hands."""
    make_user(UserRole.MANAGER, email="mgr@example.com")
    headers = login("mgr@example.com")
    assert api.get("/api/v1/admin/invites", headers=headers).status_code == 403
    assert (
        api.post(
            "/api/v1/admin/invites", json={"email": "x@example.com"}, headers=headers
        ).status_code
        == 403
    )
