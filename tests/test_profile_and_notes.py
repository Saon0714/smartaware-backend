"""Profile, onboarding wizard and notes — spec Sections 5.2, 5.3.A and 5.3.G."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_service import invalidate
from app.models.enums import UserRole
from app.models.form_schema import FormDefinition, FormField
from app.models.note import Note


@pytest.fixture(autouse=True)
def _reset() -> None:
    invalidate()


@pytest.fixture
def setup(api: TestClient, make_user, login):
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
        "client_record": client,
        "client_user": user,
    }


# --- Profile (Section 5.3.A) ------------------------------------------------------


def test_the_profile_form_comes_from_the_database(api: TestClient, setup) -> None:
    """Section 13 item 3 leaves the field list unconfirmed, so it is data."""
    body = api.get("/api/v1/portal/profile", headers=setup["client"]).json()
    keys = [f["key"] for f in body["fields"]]

    assert "company_name" in keys
    assert "owner_name" in keys
    assert body["values"]["company_name"] == "Acme Ltd"
    assert body["client_ref"].startswith("SA-")


def test_a_client_updates_their_own_profile(api: TestClient, db: Session, setup) -> None:
    response = api.patch(
        "/api/v1/portal/profile",
        json={
            "values": {
                "company_name": "Acme Holdings Ltd",
                "owner_name": "Jane Smith",
                "city": "Manchester",
            }
        },
        headers=setup["client"],
    )
    assert response.status_code == 200
    assert response.json()["values"]["company_name"] == "Acme Holdings Ltd"

    db.refresh(setup["client_record"])
    assert setup["client_record"].company_name == "Acme Holdings Ltd"
    assert setup["client_record"].city == "Manchester"


def test_a_field_added_by_an_admin_is_stored_without_a_migration(
    api: TestClient, db: Session, setup
) -> None:
    """Fields the spec did not anticipate land in `extra`, so adding one is an
    Admin Portal edit rather than a schema change."""
    form = db.execute(
        select(FormDefinition).where(FormDefinition.key == "client_profile")
    ).scalar_one()
    db.add(
        FormField(
            form_id=form.id,
            key="vat_number",
            label="VAT Number",
            field_type="text",
            sort_order=99,
        )
    )
    db.flush()

    keys = [
        f["key"]
        for f in api.get("/api/v1/portal/profile", headers=setup["client"]).json()["fields"]
    ]
    assert "vat_number" in keys

    api.patch(
        "/api/v1/portal/profile",
        json={"values": {"vat_number": "GB123456789"}},
        headers=setup["client"],
    )

    db.refresh(setup["client_record"])
    assert setup["client_record"].extra["vat_number"] == "GB123456789"


def test_unknown_profile_keys_are_ignored(api: TestClient, db: Session, setup) -> None:
    """A stale tab should still save, and nobody should be able to write
    arbitrary keys into the stored record."""
    api.patch(
        "/api/v1/portal/profile",
        json={"values": {"company_name": "Acme Ltd", "injected": "x" * 50}},
        headers=setup["client"],
    )
    db.refresh(setup["client_record"])
    assert "injected" not in (setup["client_record"].extra or {})


def test_a_required_field_cannot_be_cleared(api: TestClient, setup) -> None:
    response = api.patch(
        "/api/v1/portal/profile",
        json={"values": {"company_name": ""}},
        headers=setup["client"],
    )
    assert response.status_code == 422
    assert "Company Name" in response.json()["detail"]


def test_an_invalid_date_is_rejected(api: TestClient, setup) -> None:
    response = api.patch(
        "/api/v1/portal/profile",
        json={"values": {"registration_date": "not-a-date"}},
        headers=setup["client"],
    )
    assert response.status_code == 422


def test_a_client_cannot_reach_another_profile(api: TestClient, make_user, login, setup) -> None:
    """There is no identifier in the request — the record comes from scope."""
    make_user(UserRole.CLIENT, email="other@example.com", company_name="Other Co")
    body = api.get("/api/v1/portal/profile", headers=login("other@example.com")).json()
    assert body["values"]["company_name"] == "Other Co"


def test_staff_have_no_profile_of_their_own(api: TestClient, setup) -> None:
    assert api.get("/api/v1/portal/profile", headers=setup["admin"]).status_code == 403


# --- Onboarding wizard (Section 5.2) ------------------------------------------------


def test_the_wizard_is_served_from_the_database(api: TestClient, setup) -> None:
    body = api.get("/api/v1/portal/onboarding", headers=setup["client"]).json()
    assert [s["key"] for s in body["steps"]] == [
        "business_basics",
        "services_needed",
        "contact_preferences",
    ]
    assert body["completed_at"] is None


def test_answers_can_be_saved_without_finishing(api: TestClient, setup) -> None:
    """A long wizard should be resumable, so required answers are only checked
    at completion."""
    response = api.post(
        "/api/v1/portal/onboarding",
        json={"answers": {"entity_type": "Limited Company"}, "complete": False},
        headers=setup["client"],
    )
    assert response.status_code == 200
    assert response.json()["answers"]["entity_type"] == "Limited Company"
    assert response.json()["completed_at"] is None


def test_completing_requires_the_required_answers(api: TestClient, setup) -> None:
    response = api.post(
        "/api/v1/portal/onboarding",
        json={"answers": {"entity_type": "Limited Company"}, "complete": True},
        headers=setup["client"],
    )
    assert response.status_code == 422
    assert "primary_region" in response.json()["detail"] or "market" in response.json()["detail"]


def test_completing_marks_the_account_onboarded(api: TestClient, db: Session, setup) -> None:
    response = api.post(
        "/api/v1/portal/onboarding",
        json={
            "answers": {
                "entity_type": "Limited Company",
                "primary_region": "United Kingdom",
            },
            "complete": True,
        },
        headers=setup["client"],
    )
    assert response.status_code == 200
    assert response.json()["completed_at"] is not None

    db.refresh(setup["client_record"])
    assert setup["client_record"].onboarding_completed_at is not None


def test_answers_survive_the_wizard_being_reordered(api: TestClient, db: Session, setup) -> None:
    """Answers are keyed by question key, not position."""
    api.post(
        "/api/v1/portal/onboarding",
        json={"answers": {"entity_type": "Partnership"}, "complete": False},
        headers=setup["client"],
    )

    from app.models.onboarding import WizardStep

    steps = db.execute(select(WizardStep)).scalars().all()
    for index, step in enumerate(reversed(steps), start=1):
        step.sort_order = index
    db.flush()

    body = api.get("/api/v1/portal/onboarding", headers=setup["client"]).json()
    assert body["answers"]["entity_type"] == "Partnership"
    assert body["steps"][0]["key"] == "contact_preferences"


def test_unknown_answers_are_ignored(api: TestClient, setup) -> None:
    response = api.post(
        "/api/v1/portal/onboarding",
        json={"answers": {"made_up_question": "x"}, "complete": False},
        headers=setup["client"],
    )
    assert response.status_code == 200
    assert "made_up_question" not in response.json()["answers"]


def test_staff_can_read_a_clients_onboarding_answers(api: TestClient, setup) -> None:
    api.post(
        "/api/v1/portal/onboarding",
        json={"answers": {"entity_type": "Sole Trader"}, "complete": False},
        headers=setup["client"],
    )

    body = api.get(
        f"/api/v1/admin/clients/{setup['client_record'].id}/onboarding",
        headers=setup["manager"],
    ).json()

    answers = [a for step in body["steps"] for a in step["answers"]]
    match = next(a for a in answers if a["label"].startswith("What type of entity"))
    assert match["value"] == "Sole Trader"


def test_staff_cannot_read_onboarding_outside_their_scope(
    api: TestClient, make_user, setup
) -> None:
    _user, other = make_user(UserRole.CLIENT)
    assert (
        api.get(
            f"/api/v1/admin/clients/{other.id}/onboarding", headers=setup["manager"]
        ).status_code
        == 404
    )


def test_deactivating_a_step_hides_it_but_keeps_answers(
    api: TestClient, db: Session, setup
) -> None:
    """Clients' answers reference these questions; removing the rows would lose
    what they told us."""
    api.post(
        "/api/v1/portal/onboarding",
        json={"answers": {"notes": "Some context."}, "complete": False},
        headers=setup["client"],
    )

    steps = api.get("/api/v1/admin/wizard/steps", headers=setup["admin"]).json()
    contact = next(s for s in steps if s["key"] == "contact_preferences")
    assert (
        api.delete(
            f"/api/v1/admin/wizard/steps/{contact['id']}", headers=setup["admin"]
        ).status_code
        == 204
    )

    body = api.get("/api/v1/portal/onboarding", headers=setup["client"]).json()
    assert "contact_preferences" not in [s["key"] for s in body["steps"]]

    from app.models.onboarding import OnboardingResponse

    assert db.execute(select(OnboardingResponse)).scalars().all() != []


def test_a_new_question_appears_without_a_deploy(api: TestClient, setup) -> None:
    steps = api.get("/api/v1/admin/wizard/steps", headers=setup["admin"]).json()
    first = steps[0]

    created = api.post(
        f"/api/v1/admin/wizard/steps/{first['id']}/questions",
        json={
            "key": "turnover_band",
            "label": "Approximate annual turnover?",
            "field_type": "select",
            "options": ["Under £85k", "Over £85k"],
            "sort_order": 9,
        },
        headers=setup["admin"],
    )
    assert created.status_code == 201

    body = api.get("/api/v1/portal/onboarding", headers=setup["client"]).json()
    keys = [q["key"] for s in body["steps"] for q in s["questions"]]
    assert "turnover_band" in keys


def test_a_manager_cannot_reconfigure_the_wizard(api: TestClient, setup) -> None:
    assert api.get("/api/v1/admin/wizard/steps", headers=setup["manager"]).status_code == 403


# --- Notes (Section 5.3.G) ----------------------------------------------------------


def test_staff_create_a_note_the_client_can_read(api: TestClient, setup) -> None:
    created = api.post(
        "/api/v1/admin/notes",
        json={
            "client_id": str(setup["client_record"].id),
            "title": "VAT registration",
            "content": "Your VAT registration was accepted on 3 September.",
        },
        headers=setup["manager"],
    )
    assert created.status_code == 201

    mine = api.get("/api/v1/portal/notes", headers=setup["client"]).json()
    assert [n["title"] for n in mine] == ["VAT registration"]
    assert mine[0]["author_name"]


def test_the_client_note_view_is_read_only(api: TestClient, setup) -> None:
    """Section 5.3.G: information shared by SmartAWARE, not a conversation."""
    for method in ("POST", "PATCH", "PUT", "DELETE"):
        response = api.request(method, "/api/v1/portal/notes", json={}, headers=setup["client"])
        assert response.status_code == 405, f"{method} should not exist"


def test_a_draft_note_is_hidden_from_the_client(api: TestClient, setup) -> None:
    api.post(
        "/api/v1/admin/notes",
        json={
            "client_id": str(setup["client_record"].id),
            "content": "Internal draft.",
            "is_visible_to_client": False,
        },
        headers=setup["manager"],
    )

    assert api.get("/api/v1/portal/notes", headers=setup["client"]).json() == []
    assert len(api.get("/api/v1/admin/notes", headers=setup["manager"]).json()) == 1


def test_publishing_a_draft_reveals_it(api: TestClient, setup) -> None:
    created = api.post(
        "/api/v1/admin/notes",
        json={
            "client_id": str(setup["client_record"].id),
            "content": "Ready now.",
            "is_visible_to_client": False,
        },
        headers=setup["manager"],
    ).json()

    api.patch(
        f"/api/v1/admin/notes/{created['id']}",
        json={"is_visible_to_client": True},
        headers=setup["manager"],
    )
    assert len(api.get("/api/v1/portal/notes", headers=setup["client"]).json()) == 1


def test_a_client_cannot_read_another_clients_notes(
    api: TestClient, make_user, login, setup
) -> None:
    api.post(
        "/api/v1/admin/notes",
        json={"client_id": str(setup["client_record"].id), "content": "Private."},
        headers=setup["manager"],
    )
    make_user(UserRole.CLIENT, email="other@example.com")
    assert api.get("/api/v1/portal/notes", headers=login("other@example.com")).json() == []


def test_a_manager_cannot_write_notes_for_a_client_they_do_not_hold(
    api: TestClient, make_user, setup
) -> None:
    _user, other = make_user(UserRole.CLIENT)
    response = api.post(
        "/api/v1/admin/notes",
        json={"client_id": str(other.id), "content": "Not mine."},
        headers=setup["manager"],
    )
    assert response.status_code == 404


def test_a_client_cannot_use_the_staff_note_endpoints(api: TestClient, setup) -> None:
    assert api.get("/api/v1/admin/notes", headers=setup["client"]).status_code == 403
    assert (
        api.post(
            "/api/v1/admin/notes",
            json={"client_id": str(setup["client_record"].id), "content": "Mine."},
            headers=setup["client"],
        ).status_code
        == 403
    )


def test_notes_can_be_deleted(api: TestClient, db: Session, setup) -> None:
    """Commentary rather than a record of work, so removing one destroys no
    evidence — unlike a task or a document."""
    created = api.post(
        "/api/v1/admin/notes",
        json={"client_id": str(setup["client_record"].id), "content": "Temporary."},
        headers=setup["manager"],
    ).json()

    assert (
        api.delete(f"/api/v1/admin/notes/{created['id']}", headers=setup["manager"]).status_code
        == 204
    )
    assert db.execute(select(Note)).scalars().all() == []


# --- Assigned manager (Section 5.3.C) ------------------------------------------------

def test_the_client_sees_their_assigned_manager(api: TestClient, setup) -> None:
    body = api.get("/api/v1/portal/profile", headers=setup["client"]).json()
    assert body["assigned_manager"]["email"] == "mgr@example.com"


def test_an_unassigned_client_sees_no_manager(
    api: TestClient, make_user, login
) -> None:
    make_user(UserRole.CLIENT, email="solo@example.com")
    body = api.get("/api/v1/portal/profile", headers=login("solo@example.com")).json()
    assert body["assigned_manager"] is None


def test_an_inactive_manager_is_not_shown(
    api: TestClient, db: Session, make_user, login
) -> None:
    """Pointing a client at someone who has left is worse than showing nobody."""
    manager, _ = make_user(UserRole.MANAGER, email="leaver@example.com")
    make_user(UserRole.CLIENT, email="c2@example.com", assigned_manager=manager)

    headers = login("c2@example.com")
    assert api.get("/api/v1/portal/profile", headers=headers).json()[
        "assigned_manager"
    ]["email"] == "leaver@example.com"

    manager.is_active = False
    db.flush()

    assert api.get("/api/v1/portal/profile", headers=headers).json()[
        "assigned_manager"
    ] is None
