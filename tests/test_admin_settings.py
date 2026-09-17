"""Runtime settings management."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_service import SettingKey, get_setting, invalidate
from app.models.enums import UserRole
from app.models.setting import Setting


@pytest.fixture(autouse=True)
def _reset() -> None:
    invalidate()


@pytest.fixture
def admin_headers(api: TestClient, make_user, login) -> dict[str, str]:
    make_user(UserRole.ADMIN, email="admin@example.com")
    return login("admin@example.com")


def _patch(api: TestClient, headers, key: str, value):
    return api.patch(f"/api/v1/admin/settings/{key}", json={"value": value}, headers=headers)


# --- Permissions -----------------------------------------------------------------


def test_only_an_admin_may_manage_settings(
    api: TestClient, make_user, login, admin_headers
) -> None:
    make_user(UserRole.MANAGER, email="mgr@example.com")
    make_user(UserRole.CLIENT, email="client@example.com")

    assert api.get("/api/v1/admin/settings", headers=admin_headers).status_code == 200
    assert api.get("/api/v1/admin/settings", headers=login("mgr@example.com")).status_code == 403
    assert api.get("/api/v1/admin/settings", headers=login("client@example.com")).status_code == 403
    assert api.get("/api/v1/admin/settings").status_code == 401


# --- Listing ---------------------------------------------------------------------


def test_settings_are_grouped_with_editing_metadata(api: TestClient, admin_headers) -> None:
    """The portal needs to know a threshold is a fraction and manager scope is
    a choice, or every value renders as a text box."""
    groups = api.get("/api/v1/admin/settings", headers=admin_headers).json()
    by_key = {s["key"]: s for g in groups for s in g["settings"]}

    threshold = by_key[SettingKey.CHAT_SIMILARITY_THRESHOLD]
    assert threshold["control"] == "number"
    assert threshold["minimum"] == 0.0 and threshold["maximum"] == 1.0

    scope = by_key[SettingKey.MANAGER_CLIENT_SCOPE]
    assert scope["control"] == "choice"
    assert {c["value"] for c in scope["choices"]} == {"assigned", "all"}

    assert by_key[SettingKey.NOTIFY_ENQUIRY_RECIPIENTS]["control"] == "email_list"
    assert by_key[SettingKey.ALLOW_MULTIPLE_ADMINS]["control"] == "toggle"


def test_dangerous_settings_carry_a_confirmation(api: TestClient, admin_headers) -> None:
    groups = api.get("/api/v1/admin/settings", headers=admin_headers).json()
    by_key = {s["key"]: s for g in groups for s in g["settings"]}

    assert by_key[SettingKey.ALLOW_MULTIPLE_ADMINS]["confirm"]
    assert by_key[SettingKey.MANAGER_CLIENT_SCOPE]["confirm"]


# --- Writing ---------------------------------------------------------------------


def test_a_change_takes_effect_immediately(api: TestClient, db: Session, admin_headers) -> None:
    """Not after the read cache expires, which would look like a failed save."""
    assert _patch(api, admin_headers, SettingKey.CHAT_TOP_K, 8).status_code == 200
    assert get_setting(db, SettingKey.CHAT_TOP_K) == 8


def test_the_editor_is_recorded(api: TestClient, db: Session, admin_headers) -> None:
    _patch(api, admin_headers, SettingKey.CHAT_TOP_K, 7)
    row = db.execute(select(Setting).where(Setting.key == SettingKey.CHAT_TOP_K)).scalar_one()
    assert row.updated_by_id is not None


def test_numbers_are_range_checked(api: TestClient, admin_headers) -> None:
    assert _patch(api, admin_headers, SettingKey.CHAT_SIMILARITY_THRESHOLD, 1.5).status_code == 422
    assert _patch(api, admin_headers, SettingKey.CHAT_SIMILARITY_THRESHOLD, -0.2).status_code == 422
    assert _patch(api, admin_headers, SettingKey.CHAT_SIMILARITY_THRESHOLD, 0.4).status_code == 200


def test_a_choice_setting_rejects_anything_else(api: TestClient, admin_headers) -> None:
    refused = _patch(api, admin_headers, SettingKey.MANAGER_CLIENT_SCOPE, "everything")
    assert refused.status_code == 422
    assert "assigned" in refused.json()["detail"]
    assert _patch(api, admin_headers, SettingKey.MANAGER_CLIENT_SCOPE, "all").status_code == 200


def test_types_are_enforced(api: TestClient, admin_headers) -> None:
    assert _patch(api, admin_headers, SettingKey.CHAT_TOP_K, "eight").status_code == 422
    assert _patch(api, admin_headers, SettingKey.ALLOW_MULTIPLE_ADMINS, "yes").status_code == 422
    assert _patch(api, admin_headers, SettingKey.MANAGER_CLIENT_SCOPE, 1).status_code == 422


def test_a_boolean_cannot_masquerade_as_a_number(api: TestClient, admin_headers) -> None:
    """bool is a subclass of int in Python, so a toggle would otherwise become
    1 silently."""
    assert _patch(api, admin_headers, SettingKey.CHAT_TOP_K, True).status_code == 422


def test_unknown_settings_are_not_created(api: TestClient, admin_headers) -> None:
    """Settings are seeded. An unknown key is a typo or a stale client."""
    assert _patch(api, admin_headers, "not_a_real_setting", 1).status_code == 404


# --- Notification recipients -------------------------------------------------------


def test_recipients_are_validated_as_email_addresses(api: TestClient, admin_headers) -> None:
    """A typo here means a notification silently goes nowhere."""
    refused = _patch(
        api,
        admin_headers,
        SettingKey.NOTIFY_ENQUIRY_RECIPIENTS,
        ["team@smartaware.example", "not-an-address"],
    )
    assert refused.status_code == 422
    assert "not-an-address" in refused.json()["detail"]


def test_recipients_are_trimmed_and_deduplicated(
    api: TestClient, db: Session, admin_headers
) -> None:
    response = _patch(
        api,
        admin_headers,
        SettingKey.NOTIFY_ENQUIRY_RECIPIENTS,
        ["  team@smartaware.example  ", "team@smartaware.example", "", "b@example.com"],
    )
    assert response.status_code == 200
    assert response.json()["value"] == ["team@smartaware.example", "b@example.com"]


def test_setting_recipients_makes_enquiry_alerts_send(api: TestClient, admin_headers) -> None:
    """The point of the screen: notifications are dark until this is filled in."""
    from app.services.notification.backends import console_backend

    console_backend.clear()
    answers = {"name": "Jane Smith", "email": "jane@example.com"}

    api.post("/api/v1/public/enquiries", json={"answers": answers})
    assert console_backend.sent == [], "nothing sent while the list is empty"

    _patch(
        api,
        admin_headers,
        SettingKey.NOTIFY_ENQUIRY_RECIPIENTS,
        ["team@smartaware.example"],
    )

    from app.core import rate_limit

    rate_limit.reset("enquiry:testclient")

    api.post("/api/v1/public/enquiries", json={"answers": answers})
    assert [m.to for m in console_backend.sent] == ["team@smartaware.example"]


def test_clearing_recipients_stops_alerts_again(api: TestClient, admin_headers) -> None:
    from app.core import rate_limit
    from app.services.notification.backends import console_backend

    _patch(api, admin_headers, SettingKey.NOTIFY_ENQUIRY_RECIPIENTS, ["a@example.com"])
    _patch(api, admin_headers, SettingKey.NOTIFY_ENQUIRY_RECIPIENTS, [])

    console_backend.clear()
    rate_limit.reset("enquiry:testclient")
    api.post(
        "/api/v1/public/enquiries",
        json={"answers": {"name": "Jane", "email": "jane@example.com"}},
    )
    assert console_backend.sent == []


# --- Behavioural effect ------------------------------------------------------------


def test_changing_manager_scope_changes_what_a_manager_sees(
    api: TestClient, make_user, login, admin_headers
) -> None:
    """Settings are only worth a screen if they actually change behaviour."""
    make_user(UserRole.MANAGER, email="mgr@example.com")
    make_user(UserRole.CLIENT, company_name="Not Theirs")
    headers = login("mgr@example.com")

    assert api.get("/api/v1/admin/clients", headers=headers).json() == []

    _patch(api, admin_headers, SettingKey.MANAGER_CLIENT_SCOPE, "all")

    assert len(api.get("/api/v1/admin/clients", headers=headers).json()) == 1


def test_enabling_manager_content_access_through_the_screen(
    api: TestClient, make_user, login, admin_headers
) -> None:
    make_user(UserRole.MANAGER, email="mgr@example.com")
    headers = login("mgr@example.com")

    assert api.get("/api/v1/admin/faq", headers=headers).status_code == 403
    _patch(api, admin_headers, SettingKey.MANAGER_CAN_MANAGE_CONTENT, True)
    assert api.get("/api/v1/admin/faq", headers=headers).status_code == 200


# --- Roles requiring MFA (a picked list, not typed JSON) -----------------------


def test_mfa_roles_are_offered_as_choices(api: TestClient, admin_headers) -> None:
    """Editors pick roles; nobody should have to type a JSON array."""
    groups = api.get("/api/v1/admin/settings", headers=admin_headers).json()
    setting = next(
        s
        for group in groups
        for s in group["settings"]
        if s["key"] == SettingKey.MFA_REQUIRED_ROLES
    )
    assert setting["control"] == "multi_choice"
    assert [c["value"] for c in setting["choices"]] == ["admin", "manager", "client"]


def test_mfa_roles_are_stored_in_the_declared_order(api: TestClient, admin_headers) -> None:
    response = _patch(api, admin_headers, SettingKey.MFA_REQUIRED_ROLES, ["client", "admin"])
    assert response.status_code == 200
    assert response.json()["value"] == ["admin", "client"]


def test_mfa_roles_reject_an_unknown_role(api: TestClient, admin_headers) -> None:
    refused = _patch(api, admin_headers, SettingKey.MFA_REQUIRED_ROLES, ["admin", "auditor"])
    assert refused.status_code == 422


def test_mfa_roles_reject_a_bare_string(api: TestClient, admin_headers) -> None:
    """The old text control would have sent '["admin"]' as a string."""
    refused = _patch(api, admin_headers, SettingKey.MFA_REQUIRED_ROLES, '["admin"]')
    assert refused.status_code == 422
