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
