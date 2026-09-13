"""Public service catalogue, region resolution and overrides."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.service import Region, ServiceCategory, ServiceRegionAvailability


def test_regions_are_listed_in_order(api: TestClient) -> None:
    slugs = [r["slug"] for r in api.get("/api/v1/public/regions").json()]
    assert slugs == ["uk", "india", "uae", "oman"]


def test_hub_lists_every_category_with_its_markets(api: TestClient) -> None:
    hub = api.get("/api/v1/public/services").json()
    assert len(hub["categories"]) == 12
    assert len(hub["regions"]) == 4

    by_slug = {c["slug"]: c for c in hub["categories"]}
    assert by_slug["cis-services"]["region_slugs"] == ["uk"]
    assert set(by_slug["bookkeeping"]["region_slugs"]) == {"uk", "india", "uae", "oman"}


def test_region_page_lists_only_confirmed_services(api: TestClient) -> None:
    uk = api.get("/api/v1/public/regions/uk/services").json()
    assert uk["region"]["display_name"] == "UK Tax & Accounting Services"
    assert len(uk["services"]) == 12

    oman = api.get("/api/v1/public/regions/oman/services").json()
    slugs = [s["slug"] for s in oman["services"]]
    assert len(slugs) == 10
    assert "cis-services" not in slugs
    assert "hmrc-companies-house-compliance" not in slugs


def test_region_override_renames_the_service(api: TestClient) -> None:
    """India shows VAT / GST; the UK shows VAT. One category, two labels."""
    india = api.get("/api/v1/public/regions/india/services").json()["services"]
    uk = api.get("/api/v1/public/regions/uk/services").json()["services"]

    india_vat = next(s for s in india if s["slug"] == "vat-services")
    uk_vat = next(s for s in uk if s["slug"] == "vat-services")

    assert india_vat["name"] == "VAT / GST Services"
    assert uk_vat["name"] == "VAT Services"
    assert india_vat["id"] == uk_vat["id"], "the same row, not a duplicate"


def test_service_detail_resolves_overrides_and_bullets(api: TestClient) -> None:
    detail = api.get("/api/v1/public/regions/uk/services/personal-tax").json()
    assert detail["name"] == "Personal Tax"
    assert len(detail["details"]) == 7
    assert detail["details"][0] == "Self Assessment Tax Returns."


def test_detail_lists_other_markets_offering_the_service(api: TestClient) -> None:
    detail = api.get("/api/v1/public/regions/uk/services/bookkeeping").json()
    assert {r["slug"] for r in detail["other_regions"]} == {"india", "uae", "oman"}


def test_uk_only_service_is_404_elsewhere(api: TestClient) -> None:
    """Requesting a service a market does not offer must not fall back to a
    global page — that would contradict the brief."""
    assert api.get("/api/v1/public/regions/uk/services/cis-services").status_code == 200
    assert api.get("/api/v1/public/regions/oman/services/cis-services").status_code == 404


def test_unknown_region_and_service_are_404(api: TestClient) -> None:
    assert api.get("/api/v1/public/regions/atlantis/services").status_code == 404
    assert api.get("/api/v1/public/regions/uk/services/nope").status_code == 404


def test_subcategories_are_hidden_until_published(api: TestClient, db: Session) -> None:
    detail = api.get("/api/v1/public/regions/uk/services/payroll").json()
    assert detail["subcategories"] == []

    from app.models.service import ServiceSubcategory

    row = db.execute(
        select(ServiceSubcategory).where(ServiceSubcategory.slug == "p60-preparation")
    ).scalar_one()
    row.is_published = True
    db.flush()

    detail = api.get("/api/v1/public/regions/uk/services/payroll").json()
    assert detail["subcategories"] == ["P60 Preparation"]


def test_subcategory_availability_inherits_unless_overridden(api: TestClient, db: Session) -> None:
    """Absence of a row means "follow the parent", so only genuine exceptions
    need storing."""
    from app.models.service import ServiceSubcategory, SubcategoryRegionAvailability

    row = db.execute(
        select(ServiceSubcategory).where(ServiceSubcategory.slug == "monthly-payroll-processing")
    ).scalar_one()
    row.is_published = True
    db.flush()

    # Inherited: visible in every market offering Payroll.
    assert (
        "Monthly Payroll Processing"
        in api.get("/api/v1/public/regions/uae/services/payroll").json()["subcategories"]
    )

    uae = db.execute(select(Region).where(Region.slug == "uae")).scalar_one()
    db.add(SubcategoryRegionAvailability(subcategory_id=row.id, region_id=uae.id, is_offered=False))
    db.flush()

    assert (
        "Monthly Payroll Processing"
        not in api.get("/api/v1/public/regions/uae/services/payroll").json()["subcategories"]
    )
    assert (
        "Monthly Payroll Processing"
        in api.get("/api/v1/public/regions/uk/services/payroll").json()["subcategories"]
    )


def test_archived_service_disappears_from_the_public_site(api: TestClient, db: Session) -> None:
    category = db.execute(
        select(ServiceCategory).where(ServiceCategory.slug == "bookkeeping")
    ).scalar_one()
    category.is_archived = True
    db.flush()

    hub = api.get("/api/v1/public/services").json()
    assert "bookkeeping" not in [c["slug"] for c in hub["categories"]]
    assert api.get("/api/v1/public/regions/uk/services/bookkeeping").status_code == 404


def test_unpublished_region_is_not_reachable(api: TestClient, db: Session) -> None:
    region = db.execute(select(Region).where(Region.slug == "oman")).scalar_one()
    region.is_published = False
    db.flush()

    assert "oman" not in [r["slug"] for r in api.get("/api/v1/public/regions").json()]
    assert api.get("/api/v1/public/regions/oman/services").status_code == 404


def _availability(db: Session, region_slug: str, service_slug: str):
    return db.execute(
        select(ServiceRegionAvailability)
        .join(Region, Region.id == ServiceRegionAvailability.region_id)
        .join(
            ServiceCategory,
            ServiceCategory.id == ServiceRegionAvailability.category_id,
        )
        .where(Region.slug == region_slug, ServiceCategory.slug == service_slug)
    ).scalar_one()


def test_region_sort_override_changes_local_ordering(api: TestClient, db: Session) -> None:
    """A market can lead with what matters locally."""
    before = api.get("/api/v1/public/regions/uae/services").json()["services"]
    assert before[0]["slug"] == "personal-tax"

    _availability(db, "uae", "vat-services").sort_order = 1
    _availability(db, "uae", "personal-tax").sort_order = 5
    db.flush()

    uae = api.get("/api/v1/public/regions/uae/services").json()["services"]
    assert uae[0]["slug"] == "vat-services"

    # The UK keeps its own ordering — overrides are per market.
    assert (
        api.get("/api/v1/public/regions/uk/services").json()["services"][0]["slug"]
        == "personal-tax"
    )


def test_zero_sort_order_falls_back_to_the_category_order(api: TestClient, db: Session) -> None:
    """Switching a market on without expressing a preference should not drag
    the service to the top of that country page."""
    _availability(db, "uae", "specialist-accounting").sort_order = 0
    db.flush()

    slugs = [s["slug"] for s in api.get("/api/v1/public/regions/uae/services").json()["services"]]
    assert slugs.index("specialist-accounting") > slugs.index("personal-tax")
