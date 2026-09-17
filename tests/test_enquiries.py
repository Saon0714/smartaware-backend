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
    "additional_information": "Need help with a self assessment return.",
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
        "sub_services",
        "additional_information",
    ]


def test_service_options_come_from_the_live_taxonomy(api: TestClient) -> None:
    """So the form can never offer a service the website does not list."""
    form = api.get("/api/v1/public/forms/enquiry").json()
    field = next(f for f in form["fields"] if f["key"] == "service_required")
    assert "Personal Tax" in field["options"]
    # Thirteen names for twelve services: a market can rename one, and until
    # the person says which market they are in, both names have to be offered.
    # India lists "VAT / GST Services" where the UK lists "VAT Services".
    assert len(field["options"]) == 13
    assert {"VAT Services", "VAT / GST Services"} <= set(field["options"])


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
    assert enquiry.payload["additional_information"].startswith("Need help")
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
        json={"answers": {**VALID, "service_required": ["Something invented"]}},
    )
    assert response.status_code == 422


def test_overlong_answers_are_rejected(api: TestClient) -> None:
    response = api.post(
        "/api/v1/public/enquiries",
        json={"answers": {**VALID, "additional_information": "x" * 6000}},
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
    # Counters live in Redis with an hour-long window, so they outlive the test
    # process and must be cleared before use, not only after.
    rate_limit.reset("enquiry:203.0.113.10")
    rate_limit.reset("enquiry:203.0.113.99")

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


def test_country_options_come_from_the_served_markets(api: TestClient) -> None:
    """The field rendered as an empty dropdown before: only service_required
    was given options, so the form could not be completed."""
    form = api.get("/api/v1/public/forms/enquiry").json()
    field = next(f for f in form["fields"] if f["key"] == "country")

    assert field["options"], "country must offer choices"
    assert field["options"][:4] == [
        "United Kingdom",
        "India",
        "United Arab Emirates",
        "Oman",
    ]
    assert field["options"][-1] == "Other"


def test_unpublishing_a_market_removes_it_from_the_country_field(
    api: TestClient, db: Session
) -> None:
    from app.models.service import Region

    region = db.execute(select(Region).where(Region.slug == "oman")).scalar_one()
    region.is_published = False
    db.flush()

    form = api.get("/api/v1/public/forms/enquiry").json()
    field = next(f for f in form["fields"] if f["key"] == "country")
    assert "Oman" not in field["options"]


# --- Several services, and the specific services under them --------------------


def _catalogue(api: TestClient) -> dict:
    return api.get("/api/v1/public/enquiry-catalogue").json()


def _market(api: TestClient, country: str) -> dict:
    return next(m for m in _catalogue(api)["markets"] if m["country"] == country)


def test_the_form_asks_for_services_not_a_service(api: TestClient) -> None:
    fields = {f["key"]: f for f in api.get("/api/v1/public/forms/enquiry").json()["fields"]}
    assert fields["service_required"]["field_type"] == "multiselect"
    assert fields["sub_services"]["field_type"] == "multiselect"
    # The free-text box the service pages used to write a sentence into.
    assert "nature_of_requirement" not in fields
    assert fields["additional_information"]["is_required"] is False


def test_the_catalogue_names_a_service_the_way_its_market_does(api: TestClient) -> None:
    uk = [s["name"] for s in _market(api, "United Kingdom")["services"]]
    india = [s["name"] for s in _market(api, "India")["services"]]
    assert "VAT Services" in uk and "VAT / GST Services" not in uk
    assert "VAT / GST Services" in india and "VAT Services" not in india


def test_a_market_only_lists_what_it_offers(api: TestClient) -> None:
    uk = [s["name"] for s in _market(api, "United Kingdom")["services"]]
    india = [s["name"] for s in _market(api, "India")["services"]]
    assert "CIS Services" in uk, "CIS is a UK scheme"
    assert "CIS Services" not in india


def test_an_enquiry_can_name_several_services_and_specifics(api: TestClient, db: Session) -> None:
    india = _market(api, "India")
    vat = next(s for s in india["services"] if s["name"] == "VAT / GST Services")
    payroll = next(s for s in india["services"] if s["name"] == "Payroll")

    response = api.post(
        "/api/v1/public/enquiries",
        json={
            "answers": {
                "name": "Asha",
                "email": "asha@example.com",
                "country": "India",
                "service_required": [vat["name"], payroll["name"]],
                "sub_services": [
                    vat["sub_services"][0]["value"],
                    payroll["sub_services"][0]["value"],
                ],
            },
            "website": None,
        },
    )
    assert response.status_code == 201

    row = db.execute(select(Enquiry).where(Enquiry.email == "asha@example.com")).scalar_one()
    assert row.payload["service_required"] == ["VAT / GST Services", "Payroll"]
    assert len(row.payload["sub_services"]) == 2
    # The column exists so the Admin Portal can list without opening the
    # payload; the payload keeps the answer as it was given.
    assert row.service_required == "VAT / GST Services, Payroll"


def test_a_market_specific_name_is_accepted(api: TestClient) -> None:
    """Enquiring from India's VAT page used to be refused outright: the page
    offers "VAT / GST Services" and the check read the raw category name."""
    response = api.post(
        "/api/v1/public/enquiries",
        json={
            "answers": {
                "name": "Ravi",
                "email": "ravi@example.com",
                "country": "India",
                "service_required": ["VAT / GST Services"],
            },
            "website": None,
        },
    )
    assert response.status_code == 201


def test_a_service_that_market_does_not_offer_is_refused(api: TestClient) -> None:
    response = api.post(
        "/api/v1/public/enquiries",
        json={
            "answers": {
                "name": "Ravi",
                "email": "ravi@example.com",
                "country": "India",
                "service_required": ["CIS Services"],
            },
            "website": None,
        },
    )
    assert response.status_code == 422
    assert "CIS Services" in response.json()["detail"]


def test_a_specific_service_must_belong_to_a_chosen_service(api: TestClient) -> None:
    uk = _market(api, "United Kingdom")
    personal = next(s for s in uk["services"] if s["name"] == "Personal Tax")

    response = api.post(
        "/api/v1/public/enquiries",
        json={
            "answers": {
                "name": "Sam",
                "email": "sam@example.com",
                "country": "United Kingdom",
                "service_required": ["Payroll"],
                "sub_services": [personal["sub_services"][0]["value"]],
            },
            "website": None,
        },
    )
    assert response.status_code == 422
    assert "not offered under the services you chose" in response.json()["detail"]


def test_a_specific_service_from_another_market_is_refused(api: TestClient) -> None:
    uk = _market(api, "United Kingdom")
    cis = next(s for s in uk["services"] if s["name"] == "CIS Services")
    response = api.post(
        "/api/v1/public/enquiries",
        json={
            "answers": {
                "name": "Sam",
                "email": "sam@example.com",
                "country": "India",
                "service_required": ["Payroll"],
                "sub_services": [cis["sub_services"][0]["value"]],
            },
            "website": None,
        },
    )
    assert response.status_code == 422


def test_the_service_page_and_the_form_offer_the_same_specifics(api: TestClient) -> None:
    """An "Enquire" link can only land on an option the form actually has, and
    both lists come from one place so they cannot drift apart."""
    regions = api.get("/api/v1/public/regions").json()
    uk = next(r for r in regions if r["name"] == "United Kingdom")
    services = api.get(f"/api/v1/public/regions/{uk['slug']}/services").json()["services"]

    catalogue = {s["name"]: s for s in _market(api, "United Kingdom")["services"]}
    checked = 0
    for summary in services:
        detail = api.get(f"/api/v1/public/regions/{uk['slug']}/services/{summary['slug']}").json()
        offered = [o["label"] for o in catalogue[detail["name"]]["sub_services"]]
        assert detail["sub_services"] == offered, detail["name"]
        checked += 1
    assert checked >= 10


def test_the_specifics_are_named_so_two_services_cannot_collide(api: TestClient) -> None:
    """ "VAT Registration" sits under both VAT Services and Business
    Registration, so the name alone would not say which was meant."""
    uk = _market(api, "United Kingdom")
    values = [o["value"] for s in uk["services"] for o in s["sub_services"]]
    assert len(values) == len(set(values))
    for service in uk["services"]:
        for option in service["sub_services"]:
            assert option["value"] == f"{service['name']} — {option['label']}"
            assert option["label"] in option["value"]


def test_an_answer_the_person_never_saw_is_refused(api: TestClient) -> None:
    response = api.post(
        "/api/v1/public/enquiries",
        json={
            "answers": {
                "name": "Bot",
                "email": "bot@example.com",
                "service_required": ["Something Invented"],
            },
            "website": None,
        },
    )
    assert response.status_code == 422


def test_the_notification_lists_every_service_chosen(api: TestClient, db: Session) -> None:
    set_setting(db, SettingKey.NOTIFY_ENQUIRY_RECIPIENTS, ["team@smartaware.example"])
    db.commit()
    uk = _market(api, "United Kingdom")
    personal = next(s for s in uk["services"] if s["name"] == "Personal Tax")

    api.post(
        "/api/v1/public/enquiries",
        json={
            "answers": {
                "name": "Jo",
                "email": "jo@example.com",
                "country": "United Kingdom",
                "service_required": ["Personal Tax", "Payroll"],
                "sub_services": [personal["sub_services"][0]["value"]],
                "additional_information": "Whenever suits you.",
            },
            "website": None,
        },
    )
    body = console_backend.sent[-1].body
    assert "Personal Tax, Payroll" in body
    assert personal["sub_services"][0]["value"] in body
    assert "Whenever suits you." in body


def test_the_public_form_omits_a_retired_field(api: TestClient, db: Session) -> None:
    field = _enquiry_field(db, "additional_information")
    field.is_active = False
    db.commit()

    keys = [f["key"] for f in api.get("/api/v1/public/forms/enquiry").json()["fields"]]
    assert "additional_information" not in keys


def test_the_admin_form_shows_a_retired_field_so_it_can_come_back(
    api: TestClient, db: Session, admin_headers
) -> None:
    """Otherwise switching one off is a one-way door, and the answers older
    enquiries hold under its key have nothing left to label them."""
    retired = _enquiry_field(db, "additional_information")
    retired.is_active = False
    db.commit()

    fields = {
        f["key"]: f
        for f in api.get("/api/v1/admin/forms/enquiry", headers=admin_headers).json()["fields"]
    }
    assert fields["additional_information"]["is_active"] is False
    assert fields["additional_information"]["label"] == "Additional Information"
    assert fields["name"]["is_active"] is True

    restored = api.patch(
        f"/api/v1/admin/forms/fields/{fields['additional_information']['id']}",
        json={"is_active": True},
        headers=admin_headers,
    )
    assert restored.status_code == 200
    keys = [f["key"] for f in api.get("/api/v1/public/forms/enquiry").json()["fields"]]
    assert "additional_information" in keys
