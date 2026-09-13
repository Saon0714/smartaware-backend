"""Admin management of regions and services."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_service import invalidate
from app.models.enums import UserRole
from app.models.service import Region, ServiceCategory
from app.models.task import Task


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    invalidate()


@pytest.fixture
def admin_headers(api: TestClient, make_user, login) -> dict[str, str]:
    make_user(UserRole.ADMIN, email="admin@example.com")
    return login("admin@example.com")


def _category_id(db: Session, slug: str) -> str:
    return str(
        db.execute(select(ServiceCategory.id).where(ServiceCategory.slug == slug)).scalar_one()
    )


def _region_id(db: Session, slug: str) -> str:
    return str(db.execute(select(Region.id).where(Region.slug == slug)).scalar_one())


# --- Permissions ---------------------------------------------------------------


def test_only_content_editors_may_manage_services(
    api: TestClient, make_user, login, admin_headers
) -> None:
    make_user(UserRole.MANAGER, email="mgr@example.com")
    make_user(UserRole.CLIENT, email="client@example.com")

    assert api.get("/api/v1/admin/services", headers=admin_headers).status_code == 200
    assert api.get("/api/v1/admin/services", headers=login("mgr@example.com")).status_code == 403
    assert api.get("/api/v1/admin/services", headers=login("client@example.com")).status_code == 403
    assert api.get("/api/v1/admin/services").status_code == 401


# --- Creating and editing ------------------------------------------------------


def test_a_new_service_reaches_the_website_without_a_deploy(
    api: TestClient, db: Session, admin_headers
) -> None:
    created = api.post(
        "/api/v1/admin/services",
        json={
            "name": "Company Secretarial",
            "short_description": "Statutory company secretarial support.",
        },
        headers=admin_headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["slug"] == "company-secretarial", "slug derived from the name"

    # Not on any country page until a market is switched on.
    uk = api.get("/api/v1/public/regions/uk/services").json()["services"]
    assert "company-secretarial" not in [s["slug"] for s in uk]

    api.put(
        f"/api/v1/admin/services/{body['id']}/availability/{_region_id(db, 'uk')}",
        json={"is_offered": True},
        headers=admin_headers,
    )

    uk = api.get("/api/v1/public/regions/uk/services").json()["services"]
    assert "company-secretarial" in [s["slug"] for s in uk]
    assert api.get("/api/v1/public/regions/uk/services/company-secretarial").status_code == 200


def test_duplicate_slug_is_rejected(api: TestClient, admin_headers) -> None:
    response = api.post(
        "/api/v1/admin/services", json={"name": "Bookkeeping"}, headers=admin_headers
    )
    assert response.status_code == 409


def test_partial_update_leaves_other_fields_alone(
    api: TestClient, db: Session, admin_headers
) -> None:
    category_id = _category_id(db, "payroll")
    updated = api.patch(
        f"/api/v1/admin/services/{category_id}",
        json={"short_description": "Reworded payroll blurb."},
        headers=admin_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["short_description"] == "Reworded payroll blurb."
    assert updated.json()["name"] == "Payroll"


def test_editing_a_service_changes_the_public_page(
    api: TestClient, db: Session, admin_headers
) -> None:
    api.patch(
        f"/api/v1/admin/services/{_category_id(db, 'payroll')}",
        json={"name": "Payroll & PAYE"},
        headers=admin_headers,
    )
    detail = api.get("/api/v1/public/regions/uk/services/payroll").json()
    assert detail["name"] == "Payroll & PAYE"


# --- Archiving (the "delete" button) -------------------------------------------


def test_delete_archives_and_hides_the_service(api: TestClient, db: Session, admin_headers) -> None:
    category_id = _category_id(db, "bookkeeping")
    response = api.delete(f"/api/v1/admin/services/{category_id}", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["is_archived"] is True
    assert response.json()["is_published"] is False

    hub = api.get("/api/v1/public/services").json()
    assert "bookkeeping" not in [c["slug"] for c in hub["categories"]]


def test_archived_service_is_hidden_from_the_default_admin_list(
    api: TestClient, db: Session, admin_headers
) -> None:
    category_id = _category_id(db, "bookkeeping")
    api.delete(f"/api/v1/admin/services/{category_id}", headers=admin_headers)

    default = api.get("/api/v1/admin/services", headers=admin_headers).json()
    assert "bookkeeping" not in [c["slug"] for c in default]

    including = api.get(
        "/api/v1/admin/services?include_archived=true", headers=admin_headers
    ).json()
    assert "bookkeeping" in [c["slug"] for c in including]


def test_archived_service_can_be_restored(api: TestClient, db: Session, admin_headers) -> None:
    category_id = _category_id(db, "bookkeeping")
    api.delete(f"/api/v1/admin/services/{category_id}", headers=admin_headers)

    restored = api.post(f"/api/v1/admin/services/{category_id}/restore", headers=admin_headers)
    assert restored.status_code == 200
    assert restored.json()["is_archived"] is False


def test_hard_delete_is_refused_while_tasks_reference_the_service(
    api: TestClient, db: Session, make_user, admin_headers
) -> None:
    """The reason "delete" archives: destroying the row would corrupt the
    record of completed work."""
    user, client = make_user(UserRole.CLIENT)
    category_id = _category_id(db, "bookkeeping")
    db.add(Task(client_id=client.id, title="FY24 books", service_category_id=category_id))
    db.flush()

    response = api.delete(f"/api/v1/admin/services/{category_id}?hard=true", headers=admin_headers)
    assert response.status_code == 409
    assert "task(s) reference this service" in response.json()["detail"]

    assert db.get(ServiceCategory, category_id) is not None


def test_hard_delete_is_allowed_when_nothing_references_it(api: TestClient, admin_headers) -> None:
    created = api.post(
        "/api/v1/admin/services", json={"name": "Temporary Service"}, headers=admin_headers
    ).json()
    response = api.delete(
        f"/api/v1/admin/services/{created['id']}?hard=true", headers=admin_headers
    )
    assert response.status_code == 200
    assert (
        api.get(f"/api/v1/admin/services/{created['id']}", headers=admin_headers).status_code == 404
    )


# --- Availability grid ---------------------------------------------------------


def test_availability_grid_shows_every_region_including_unset(
    api: TestClient, db: Session, admin_headers
) -> None:
    """An editor needs to see what is switched off, not only what is on."""
    grid = api.get(
        f"/api/v1/admin/services/{_category_id(db, 'cis-services')}/availability",
        headers=admin_headers,
    ).json()

    assert len(grid["regions"]) == 4
    offered = {r["region_slug"]: r["is_offered"] for r in grid["regions"]}
    assert offered == {"uk": True, "india": False, "uae": False, "oman": False}


def test_availability_is_an_upsert(api: TestClient, db: Session, admin_headers) -> None:
    category_id = _category_id(db, "cis-services")
    oman_id = _region_id(db, "oman")

    # No row exists yet for this pair.
    created = api.put(
        f"/api/v1/admin/services/{category_id}/availability/{oman_id}",
        json={"is_offered": True},
        headers=admin_headers,
    )
    assert created.status_code == 200
    assert api.get("/api/v1/public/regions/oman/services/cis-services").status_code == 200

    # Same call again updates rather than duplicating.
    api.put(
        f"/api/v1/admin/services/{category_id}/availability/{oman_id}",
        json={"is_offered": False},
        headers=admin_headers,
    )
    assert api.get("/api/v1/public/regions/oman/services/cis-services").status_code == 404


def test_override_changes_only_the_named_market(
    api: TestClient, db: Session, admin_headers
) -> None:
    category_id = _category_id(db, "payroll")
    api.put(
        f"/api/v1/admin/services/{category_id}/availability/{_region_id(db, 'uae')}",
        json={"is_offered": True, "name_override": "Payroll & WPS"},
        headers=admin_headers,
    )

    assert api.get("/api/v1/public/regions/uae/services/payroll").json()["name"] == "Payroll & WPS"
    assert api.get("/api/v1/public/regions/uk/services/payroll").json()["name"] == "Payroll"


# --- Subcategories and bullets -------------------------------------------------


def test_subcategory_can_be_added_and_published(
    api: TestClient, db: Session, admin_headers
) -> None:
    category_id = _category_id(db, "payroll")
    created = api.post(
        f"/api/v1/admin/services/{category_id}/subcategories",
        json={"name": "Directors Payroll Review"},
        headers=admin_headers,
    )
    assert created.status_code == 201
    assert created.json()["slug"] == "directors-payroll-review"
    assert created.json()["is_published"] is False, "internal until published"

    api.patch(
        f"/api/v1/admin/services/subcategories/{created.json()['id']}",
        json={"name": "Directors Payroll Review", "is_published": True},
        headers=admin_headers,
    )
    detail = api.get("/api/v1/public/regions/uk/services/payroll").json()
    assert "Directors Payroll Review" in detail["subcategories"]


def test_subcategory_delete_archives_it(api: TestClient, db: Session, admin_headers) -> None:
    category_id = _category_id(db, "payroll")
    created = api.post(
        f"/api/v1/admin/services/{category_id}/subcategories",
        json={"name": "Temporary", "is_published": True},
        headers=admin_headers,
    ).json()

    archived = api.delete(
        f"/api/v1/admin/services/subcategories/{created['id']}", headers=admin_headers
    )
    assert archived.status_code == 200
    assert archived.json()["is_archived"] is True


def test_detail_bullets_can_be_added_and_removed(
    api: TestClient, db: Session, admin_headers
) -> None:
    category_id = _category_id(db, "payroll")
    created = api.post(
        f"/api/v1/admin/services/{category_id}/details",
        json={"text": "Workplace pension re-enrolment.", "sort_order": 9},
        headers=admin_headers,
    )
    assert created.status_code == 201

    detail = api.get("/api/v1/public/regions/uk/services/payroll").json()
    assert "Workplace pension re-enrolment." in detail["details"]

    api.delete(f"/api/v1/admin/services/details/{created.json()['id']}", headers=admin_headers)
    detail = api.get("/api/v1/public/regions/uk/services/payroll").json()
    assert "Workplace pension re-enrolment." not in detail["details"]


# --- Regions -------------------------------------------------------------------


def test_a_new_region_can_be_added_without_a_migration(api: TestClient, admin_headers) -> None:
    """Regions are rows precisely so opening a market is data entry."""
    created = api.post(
        "/api/v1/admin/regions",
        json={
            "slug": "qatar",
            "name": "Qatar",
            "display_name": "Qatar Tax & Accounting Services",
            "currency_code": "QAR",
            "sort_order": 5,
        },
        headers=admin_headers,
    )
    assert created.status_code == 201
    assert "qatar" in [r["slug"] for r in api.get("/api/v1/public/regions").json()]
    assert api.get("/api/v1/public/regions/qatar/services").json()["services"] == []


def test_duplicate_region_slug_is_rejected(api: TestClient, admin_headers) -> None:
    response = api.post(
        "/api/v1/admin/regions",
        json={"slug": "uk", "name": "Duplicate", "display_name": "Duplicate"},
        headers=admin_headers,
    )
    assert response.status_code == 409


def test_reorder_rewrites_service_order(api: TestClient, db: Session, admin_headers) -> None:
    current = api.get("/api/v1/admin/services", headers=admin_headers).json()
    reversed_ids = [c["id"] for c in reversed(current)]

    response = api.post(
        "/api/v1/admin/services/reorder",
        json={"ids": reversed_ids},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert [c["id"] for c in response.json()] == reversed_ids
