"""The enquiry form and the notification it triggers."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.settings_service import SettingKey, invalidate, set_setting
from app.models.enquiry import Enquiry
from app.models.enums import UserRole
from app.models.form_schema import FormDefinition, FormField
from app.services.notification.backends import console_backend

#: TestClient always presents the same host, so without a reset the rate
#: limiter would carry a count across tests and fail whichever ran sixth.
TEST_CLIENT_IP = "testclient"


@pytest.fixture(autouse=True)
def _reset() -> None:
    invalidate()
    console_backend.clear()
    rate_limit.reset(f"enquiry:{TEST_CLIENT_IP}")


@pytest.fixture
def admin_headers(api: TestClient, make_user, login) -> dict[str, str]:
    make_user(UserRole.ADMIN, email="admin@example.com")
    return login("admin@example.com")


def _enquiry_field(db: Session, key: str) -> FormField:
    """Scoped to the enquiry form.

    `company_name` also exists on the client_profile form, so querying by key
    alone matches two rows.
    """
    return db.execute(
        select(FormField)
        .join(FormDefinition, FormDefinition.id == FormField.form_id)
        .where(FormDefinition.key == "enquiry", FormField.key == key)
    ).scalar_one()


VALID = {
    "name": "Jane Smith",
    "email": "jane@example.com",
    "phone": "+44 7700 900000",
    "country": "United Kingdom",
    "company_name": "Smith Ltd",
    "nature_of_requirement": "Need help with a self assessment return.",
}


# --- The form definition --------------------------------------------------------


def test_form_definition_is_served_from_the_database(api: TestClient) -> None:
    form = api.get("/api/v1/public/forms/enquiry").json()
    keys = [f["key"] for f in form["fields"]]
    assert keys == [
        "name",
        "email",
        "phone",
        "country",
        "company_name",
        "service_required",
        "nature_of_requirement",
        "additional_information",
    ]


def test_service_options_come_from_the_live_taxonomy(api: TestClient) -> None:
    """So the form can never offer a service the website does not list."""
    form = api.get("/api/v1/public/forms/enquiry").json()
    field = next(f for f in form["fields"] if f["key"] == "service_required")
    assert "Personal Tax" in field["options"]
    assert len(field["options"]) == 12


def test_archiving_a_service_removes_it_from_the_form(
    api: TestClient, db: Session, admin_headers
) -> None:
    services = api.get("/api/v1/admin/services", headers=admin_headers).json()
    bookkeeping = next(s for s in services if s["slug"] == "bookkeeping")
    api.delete(f"/api/v1/admin/services/{bookkeeping['id']}", headers=admin_headers)

    form = api.get("/api/v1/public/forms/enquiry").json()
    field = next(f for f in form["fields"] if f["key"] == "service_required")
    assert "Bookkeeping" not in field["options"]


def test_unknown_form_is_404(api: TestClient) -> None:
    assert api.get("/api/v1/public/forms/nope").status_code == 404


# --- Submitting -----------------------------------------------------------------


def test_a_valid_submission_is_stored(api: TestClient, db: Session) -> None:
    response = api.post("/api/v1/public/enquiries", json={"answers": VALID})
    assert response.status_code == 201

    enquiry = db.execute(select(Enquiry)).scalar_one()
    assert enquiry.name == "Jane Smith"
    assert enquiry.email == "jane@example.com"
    assert enquiry.payload["nature_of_requirement"].startswith("Need help")
    assert enquiry.is_handled is False


def test_submission_needs_no_authentication(api: TestClient) -> None:
    assert api.post("/api/v1/public/enquiries", json={"answers": VALID}).status_code == 201


def test_required_fields_are_enforced_from_the_definition(api: TestClient) -> None:
    response = api.post("/api/v1/public/enquiries", json={"answers": {"phone": "123"}})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "Name" in detail and "Email" in detail


def test_making_a_field_required_takes_effect_immediately(
    api: TestClient, db: Session, admin_headers
) -> None:
    """The point of a database-driven form."""
    assert api.post("/api/v1/public/enquiries", json={"answers": VALID}).status_code == 201

    field = _enquiry_field(db, "company_name")
    api.patch(
        f"/api/v1/admin/forms/fields/{field.id}",
        json={"is_required": True},
        headers=admin_headers,
    )

    without_company = {k: v for k, v in VALID.items() if k != "company_name"}
    response = api.post("/api/v1/public/enquiries", json={"answers": without_company})
    assert response.status_code == 422
    assert "Company Name" in response.json()["detail"]


def test_a_new_field_is_accepted_without_a_deploy(api: TestClient, admin_headers) -> None:
    created = api.post(
        "/api/v1/admin/forms/enquiry/fields",
        json={
            "key": "referred_by",
            "label": "How did you hear about us?",
            "field_type": "text",
            "sort_order": 9,
        },
        headers=admin_headers,
    )
    assert created.status_code == 201

    form = api.get("/api/v1/public/forms/enquiry").json()
    assert "referred_by" in [f["key"] for f in form["fields"]]

    response = api.post(
        "/api/v1/public/enquiries",
        json={"answers": {**VALID, "referred_by": "A colleague"}},
    )
    assert response.status_code == 201


def test_unknown_answers_are_dropped_not_rejected(api: TestClient, db: Session) -> None:
    """A stale tab holding a removed field should still submit, and nobody
    should be able to write arbitrary keys into the payload column."""
    response = api.post(
        "/api/v1/public/enquiries",
        json={"answers": {**VALID, "injected": "x" * 100, "another": "y"}},
    )
    assert response.status_code == 201

    enquiry = db.execute(select(Enquiry)).scalar_one()
    assert "injected" not in enquiry.payload
    assert "another" not in enquiry.payload


def test_deactivated_field_disappears_but_history_survives(
    api: TestClient, db: Session, admin_headers
) -> None:
    api.post("/api/v1/public/enquiries", json={"answers": VALID})

    field = _enquiry_field(db, "company_name")
    api.delete(f"/api/v1/admin/forms/fields/{field.id}", headers=admin_headers)

    form = api.get("/api/v1/public/forms/enquiry").json()
    assert "company_name" not in [f["key"] for f in form["fields"]]

    stored = db.execute(select(Enquiry)).scalar_one()
    assert stored.payload["company_name"] == "Smith Ltd"


def test_service_required_must_be_a_real_service(api: TestClient) -> None:
    response = api.post(
        "/api/v1/public/enquiries",
        json={"answers": {**VALID, "service_required": "Something invented"}},
    )
    assert response.status_code == 422


def test_overlong_answers_are_rejected(api: TestClient) -> None:
    response = api.post(
        "/api/v1/public/enquiries",
        json={"answers": {**VALID, "nature_of_requirement": "x" * 6000}},
    )
    assert response.status_code == 422


def test_honeypot_submissions_are_silently_discarded(api: TestClient, db: Session) -> None:
    """Answering as though it worked, so a bot author learns nothing."""
    response = api.post(
        "/api/v1/public/enquiries",
        json={"answers": VALID, "website": "http://spam.example"},
    )
    assert response.status_code == 201
    assert db.execute(select(Enquiry)).first() is None


# --- Notification ----------------------------------------------------------------


def test_nothing_is_sent_until_recipients_are_configured(api: TestClient, db: Session) -> None:
    """Seeded empty, so the system cannot email an address nobody chose."""
    api.post("/api/v1/public/enquiries", json={"answers": VALID})
    assert console_backend.sent == []


def test_configured_recipients_receive_the_enquiry(api: TestClient, db: Session) -> None:
    set_setting(db, SettingKey.NOTIFY_ENQUIRY_RECIPIENTS, ["team@smartaware.example"])
    db.commit()

    api.post("/api/v1/public/enquiries", json={"answers": VALID})

    assert [m.to for m in console_backend.sent] == ["team@smartaware.example"]
    message = console_backend.sent[0]
    assert "Jane Smith" in message.subject
    assert "jane@example.com" in message.body
    assert "Need help with a self assessment return." in message.body


def test_a_failing_notification_does_not_lose_the_enquiry(
    api: TestClient, db: Session, monkeypatch
) -> None:
    set_setting(db, SettingKey.NOTIFY_ENQUIRY_RECIPIENTS, ["team@example.com"])
    db.commit()

    def explode(**_kwargs):
        raise RuntimeError("SES is down")

    monkeypatch.setattr(console_backend, "send", explode)

    response = api.post("/api/v1/public/enquiries", json={"answers": VALID})
    assert response.status_code == 201
    assert db.execute(select(Enquiry)).scalar_one() is not None


# --- Admin --------------------------------------------------------------------


def test_admin_can_list_and_triage_enquiries(api: TestClient, admin_headers) -> None:
    api.post("/api/v1/public/enquiries", json={"answers": VALID})

    rows = api.get("/api/v1/admin/enquiries", headers=admin_headers).json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Jane Smith"

    updated = api.patch(
        f"/api/v1/admin/enquiries/{rows[0]['id']}",
        json={"is_handled": True, "internal_note": "Called back."},
        headers=admin_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["is_handled"] is True

    assert api.get("/api/v1/admin/enquiries?handled=false", headers=admin_headers).json() == []


def test_manager_may_view_enquiries(api: TestClient, make_user, login) -> None:
    """Section 6.1 grants managers enquiry visibility."""
    make_user(UserRole.MANAGER, email="mgr@example.com")
    assert api.get("/api/v1/admin/enquiries", headers=login("mgr@example.com")).status_code == 200


def test_client_cannot_read_enquiries(api: TestClient, make_user, login) -> None:
    make_user(UserRole.CLIENT, email="client@example.com")
    assert (
        api.get("/api/v1/admin/enquiries", headers=login("client@example.com")).status_code == 403
    )


def test_anonymous_cannot_read_enquiries(api: TestClient) -> None:
    assert api.get("/api/v1/admin/enquiries").status_code == 401


def test_manager_cannot_edit_form_fields_by_default(api: TestClient, make_user, login) -> None:
    make_user(UserRole.MANAGER, email="mgr@example.com")
    assert (
        api.post(
            "/api/v1/admin/forms/enquiry/fields",
            json={"key": "x", "label": "X", "field_type": "text"},
            headers=login("mgr@example.com"),
        ).status_code
        == 403
    )


# --- Abuse protection ------------------------------------------------------------


def test_repeated_submissions_are_rate_limited(api: TestClient) -> None:
    """A public write endpoint is an obvious spam target: unchecked, it fills
    the Admin Portal and, once recipients are set, floods their inbox."""
    for _ in range(5):
        assert api.post("/api/v1/public/enquiries", json={"answers": VALID}).status_code == 201

    blocked = api.post("/api/v1/public/enquiries", json={"answers": VALID})
    assert blocked.status_code == 429


def test_rate_limit_is_scoped_per_caller(api: TestClient) -> None:
    """The limit follows the forwarded client address, not the load balancer,
    so one noisy visitor cannot lock everyone else out."""
    for _ in range(5):
        api.post(
            "/api/v1/public/enquiries",
            json={"answers": VALID},
            headers={"X-Forwarded-For": "203.0.113.10"},
        )
    rate_limit.reset("enquiry:203.0.113.10")

    other = api.post(
        "/api/v1/public/enquiries",
        json={"answers": VALID},
        headers={"X-Forwarded-For": "203.0.113.99"},
    )
    assert other.status_code == 201
