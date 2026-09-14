"""Seed data and the service taxonomy."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.content import (
    Achievement,
    ContentBlock,
    CoreValue,
    KeyStrength,
    LegalPage,
    Milestone,
    Qualification,
    TeamMember,
    Testimonial,
)
from app.models.service import (
    Region,
    ServiceCategory,
    ServiceRegionAvailability,
    ServiceSubcategory,
)
from app.models.setting import Setting
from app.seeds.run import seed_all


def _count(db: Session, model) -> int:
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def test_seed_creates_taxonomy(seeded_db: Session) -> None:
    assert _count(seeded_db, Region) == 4
    assert _count(seeded_db, ServiceCategory) == 12
    assert _count(seeded_db, ServiceSubcategory) == 214


def test_seed_is_idempotent(seeded_db: Session) -> None:
    """Re-running must never duplicate rows or overwrite admin edits."""
    before = (
        _count(seeded_db, ServiceCategory),
        _count(seeded_db, ServiceSubcategory),
        _count(seeded_db, ContentBlock),
        _count(seeded_db, Setting),
    )
    seed_all(seeded_db)
    after = (
        _count(seeded_db, ServiceCategory),
        _count(seeded_db, ServiceSubcategory),
        _count(seeded_db, ContentBlock),
        _count(seeded_db, Setting),
    )
    assert before == after


def test_seed_does_not_overwrite_edited_content(seeded_db: Session) -> None:
    block = seeded_db.execute(select(ContentBlock).where(ContentBlock.key == "vision")).scalar_one()
    block.body = "Edited by SmartAWARE via the Admin Portal"
    seeded_db.flush()

    seed_all(seeded_db)

    reloaded = seeded_db.execute(
        select(ContentBlock).where(ContentBlock.key == "vision")
    ).scalar_one()
    assert reloaded.body == "Edited by SmartAWARE via the Admin Portal"


def _offered_regions(db: Session, category_slug: str) -> set[str]:
    rows = db.execute(
        select(Region.slug)
        .join(ServiceRegionAvailability, ServiceRegionAvailability.region_id == Region.id)
        .join(ServiceCategory, ServiceCategory.id == ServiceRegionAvailability.category_id)
        .where(ServiceCategory.slug == category_slug)
        .where(ServiceRegionAvailability.is_offered.is_(True))
    ).scalars()
    return set(rows)


def test_cis_is_uk_only(seeded_db: Session) -> None:
    """The brief is explicit that a service appears only where it applies."""
    assert _offered_regions(seeded_db, "cis-services") == {"uk"}


def test_hmrc_compliance_not_offered_in_gulf(seeded_db: Session) -> None:
    assert _offered_regions(seeded_db, "hmrc-companies-house-compliance") == {"uk", "india"}


def test_uk_offers_every_category(seeded_db: Session) -> None:
    uk_count = seeded_db.execute(
        select(func.count())
        .select_from(ServiceRegionAvailability)
        .join(Region, Region.id == ServiceRegionAvailability.region_id)
        .where(Region.slug == "uk")
    ).scalar_one()
    assert uk_count == 12


def test_india_renames_vat_to_include_gst(seeded_db: Session) -> None:
    """Region overrides let one category carry local naming without duplication."""
    override = seeded_db.execute(
        select(ServiceRegionAvailability.name_override)
        .join(Region, Region.id == ServiceRegionAvailability.region_id)
        .join(ServiceCategory, ServiceCategory.id == ServiceRegionAvailability.category_id)
        .where(Region.slug == "india", ServiceCategory.slug == "vat-services")
    ).scalar_one()
    assert override == "VAT / GST Services"

    uk_override = seeded_db.execute(
        select(ServiceRegionAvailability.name_override)
        .join(Region, Region.id == ServiceRegionAvailability.region_id)
        .join(ServiceCategory, ServiceCategory.id == ServiceRegionAvailability.category_id)
        .where(Region.slug == "uk", ServiceCategory.slug == "vat-services")
    ).scalar_one()
    assert uk_override is None


def test_subcategories_are_internal_by_default(seeded_db: Session) -> None:
    """Categories are public; subcategories drive task categorisation."""
    published = seeded_db.execute(
        select(func.count())
        .select_from(ServiceSubcategory)
        .where(ServiceSubcategory.is_published.is_(True))
    ).scalar_one()
    assert published == 0

    unpublished_categories = seeded_db.execute(
        select(func.count())
        .select_from(ServiceCategory)
        .where(ServiceCategory.is_published.is_(False))
    ).scalar_one()
    assert unpublished_categories == 0


def test_brief_prose_is_seeded(seeded_db: Session) -> None:
    assert _count(seeded_db, CoreValue) == 6
    assert _count(seeded_db, KeyStrength) == 7
    assert _count(seeded_db, Milestone) == 3

    about = seeded_db.execute(
        select(ContentBlock).where(ContentBlock.key == "about_intro")
    ).scalar_one()
    assert "Established in 2016" in (about.body or "")


def test_unverified_content_is_not_fabricated(seeded_db: Session) -> None:
    """The brief permits only verified credentials and achievements to be
    published. These tables ship empty so nothing invented can reach the site."""
    assert _count(seeded_db, TeamMember) == 0
    assert _count(seeded_db, Qualification) == 0
    assert _count(seeded_db, Achievement) == 0


def test_seeded_testimonials_are_marked_as_placeholders(seeded_db: Session) -> None:
    """Testimonials ship with content so the carousel can be seen working before
    Trustpilot is connected.

    They read as ordinary reviews — that is the point of sample copy — so the
    marker is `source`, not the wording. It is what the Trustpilot import uses
    to clear them on its first successful run, and what the Admin Portal lists
    against each row. Nothing else distinguishes them, so this is the assertion
    that has to hold.

    No named individual is invented: each is attributed to a role at a company
    that does not exist. Putting words in the mouth of a person who does not
    exist is a different thing from sample copy, and the empty team and
    qualification tables above exist to prevent exactly that.
    """
    rows = list(seeded_db.execute(select(Testimonial)).scalars())
    assert rows, "seeded, so the carousel is visible before Trustpilot"

    for row in rows:
        assert row.source == "placeholder", row.author_company
        assert row.external_id is None, "not pretending to have come from anywhere"
        assert row.author_company, "attributed to a company, not to a person"


def test_legal_pages_are_unpublished_placeholders(seeded_db: Session) -> None:
    pages = list(seeded_db.execute(select(LegalPage)).scalars())
    assert {p.slug for p in pages} == {"privacy-policy", "cookie-policy", "terms-of-service"}
    for page in pages:
        assert page.is_published is False
        assert "PLACEHOLDER" in page.body
