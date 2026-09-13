"""Login, sessions and account gating."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.enums import ClientStatus, UserRole

PASSWORD = "correct horse battery staple"


def test_login_returns_access_token_and_sets_refresh_cookie(api: TestClient, make_user) -> None:
    make_user(UserRole.ADMIN, email="a@example.com")

    response = api.post("/api/v1/auth/login", json={"email": "a@example.com", "password": PASSWORD})
    assert response.status_code == 200

    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["role"] == "admin"
    assert settings.REFRESH_COOKIE_NAME in response.cookies


def test_refresh_token_is_httponly_and_absent_from_the_body(api: TestClient, make_user) -> None:
    """The whole point of the cookie is that page JavaScript cannot read it."""
    make_user(UserRole.ADMIN, email="a@example.com")
    response = api.post("/api/v1/auth/login", json={"email": "a@example.com", "password": PASSWORD})

    assert "refresh_token" not in response.json()
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie


def test_wrong_password_is_rejected(api: TestClient, make_user) -> None:
    make_user(UserRole.ADMIN, email="a@example.com")
    response = api.post(
        "/api/v1/auth/login", json={"email": "a@example.com", "password": "wrong-password"}
    )
    assert response.status_code == 401


def test_unknown_and_wrong_password_are_indistinguishable(api: TestClient, make_user) -> None:
    """Identical responses, so the endpoint cannot enumerate accounts."""
    make_user(UserRole.ADMIN, email="a@example.com")

    wrong = api.post(
        "/api/v1/auth/login", json={"email": "a@example.com", "password": "wrong-password"}
    )
    missing = api.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"}
    )

    assert wrong.status_code == missing.status_code == 401
    assert wrong.json()["detail"] == missing.json()["detail"]


# --- Account status gating (Section 6.2) -------------------------------------


def test_client_on_hold_cannot_log_in(api: TestClient, make_user) -> None:
    make_user(UserRole.CLIENT, email="hold@example.com", client_status=ClientStatus.HOLD)
    response = api.post(
        "/api/v1/auth/login", json={"email": "hold@example.com", "password": PASSWORD}
    )
    assert response.status_code == 403
    assert "hold" in response.json()["detail"].lower()


def test_deactivated_client_cannot_log_in(api: TestClient, make_user) -> None:
    make_user(UserRole.CLIENT, email="gone@example.com", client_status=ClientStatus.DEACTIVE)
    response = api.post(
        "/api/v1/auth/login", json={"email": "gone@example.com", "password": PASSWORD}
    )
    assert response.status_code == 403


def test_hold_and_deactive_block_login_identically(api: TestClient, make_user) -> None:
    """Section 6.2: they differ in business meaning, not in access behaviour."""
    make_user(UserRole.CLIENT, email="h@example.com", client_status=ClientStatus.HOLD)
    make_user(UserRole.CLIENT, email="d@example.com", client_status=ClientStatus.DEACTIVE)

    hold = api.post("/api/v1/auth/login", json={"email": "h@example.com", "password": PASSWORD})
    deactive = api.post("/api/v1/auth/login", json={"email": "d@example.com", "password": PASSWORD})
    assert hold.status_code == deactive.status_code == 403


def test_putting_a_client_on_hold_cuts_off_an_existing_session(
    api: TestClient, db: Session, make_user, login
) -> None:
    """Status is re-checked on every request, so Hold takes effect at once
    rather than when the access token happens to expire."""
    _, client = make_user(UserRole.CLIENT, email="active@example.com")
    headers = login("active@example.com")

    assert api.get("/api/v1/auth/me", headers=headers).status_code == 200

    client.status = ClientStatus.HOLD
    db.flush()

    blocked = api.get("/api/v1/auth/me", headers=headers)
    assert blocked.status_code == 403


def test_deactivating_a_staff_user_cuts_off_their_session(
    api: TestClient, db: Session, make_user, login
) -> None:
    manager, _ = make_user(UserRole.MANAGER, email="m@example.com")
    headers = login("m@example.com")
    assert api.get("/api/v1/auth/me", headers=headers).status_code == 200

    manager.is_active = False
    db.flush()

    assert api.get("/api/v1/auth/me", headers=headers).status_code == 403


# --- Tokens -------------------------------------------------------------------


def test_me_requires_authentication(api: TestClient) -> None:
    assert api.get("/api/v1/auth/me").status_code == 401


def test_garbage_token_is_rejected(api: TestClient) -> None:
    response = api.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_refresh_token_is_not_accepted_as_an_access_token(api: TestClient, make_user) -> None:
    """Otherwise the session would silently last the refresh lifetime."""
    make_user(UserRole.ADMIN, email="a@example.com")
    api.post("/api/v1/auth/login", json={"email": "a@example.com", "password": PASSWORD})
    refresh_token = api.cookies[settings.REFRESH_COOKIE_NAME]

    response = api.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh_token}"})
    assert response.status_code == 401


def test_refresh_issues_a_new_access_token(api: TestClient, make_user) -> None:
    make_user(UserRole.ADMIN, email="a@example.com")
    api.post("/api/v1/auth/login", json={"email": "a@example.com", "password": PASSWORD})

    response = api.post("/api/v1/auth/refresh")
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_refresh_without_a_cookie_is_rejected(api: TestClient) -> None:
    assert api.post("/api/v1/auth/refresh").status_code == 401


def test_logout_clears_the_cookie(api: TestClient, make_user) -> None:
    make_user(UserRole.ADMIN, email="a@example.com")
    api.post("/api/v1/auth/login", json={"email": "a@example.com", "password": PASSWORD})

    api.post("/api/v1/auth/logout")
    assert api.post("/api/v1/auth/refresh").status_code == 401


# --- Password change ----------------------------------------------------------


def test_change_password_revokes_other_sessions(api: TestClient, make_user, login) -> None:
    make_user(UserRole.ADMIN, email="a@example.com")
    headers = login("a@example.com")

    response = api.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "an even longer passphrase"},
        headers=headers,
    )
    assert response.status_code == 200

    # The old access token was minted against the previous token_version.
    assert api.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_change_password_requires_the_current_one(api: TestClient, make_user, login) -> None:
    make_user(UserRole.ADMIN, email="a@example.com")
    headers = login("a@example.com")

    response = api.post(
        "/api/v1/auth/change-password",
        json={"current_password": "not-it", "new_password": "an even longer passphrase"},
        headers=headers,
    )
    assert response.status_code == 400


def test_short_passwords_are_rejected(api: TestClient, make_user, login) -> None:
    make_user(UserRole.ADMIN, email="a@example.com")
    headers = login("a@example.com")

    response = api.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "short"},
        headers=headers,
    )
    assert response.status_code == 422
