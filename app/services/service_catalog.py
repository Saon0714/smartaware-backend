"""Reading the service taxonomy.

Two rules are enforced here rather than in route handlers, because getting
either wrong would put a service in front of the wrong market:

  * A category appears in a market only when an availability row says so. The
    content brief is explicit that a country page shows a service only once
    SmartAWARE confirms it applies there, so absence means hidden.
  * Overrides are resolved before the data leaves this module. Callers receive
    the name and wording that market should display and never need to know an
    override existed.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.service import (
    Region,
    ServiceCategory,
    ServiceDetail,
    ServiceRegionAvailability,
    ServiceSubcategory,
    SubcategoryRegionAvailability,
)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def _live_categories():
    """Categories eligible for the public site."""
    return (
        ServiceCategory.is_published.is_(True),
        ServiceCategory.is_archived.is_(False),
    )


def published_regions(db: Session) -> list[Region]:
    return list(
        db.execute(
            select(Region)
            .where(Region.is_published.is_(True))
            .order_by(Region.sort_order, Region.name)
        ).scalars()
    )


def get_region(db: Session, slug: str) -> Region | None:
    return db.execute(
        select(Region).where(Region.slug == slug, Region.is_published.is_(True))
    ).scalar_one_or_none()


def live_categories(db: Session) -> list[ServiceCategory]:
    return list(
        db.execute(
            select(ServiceCategory)
            .where(*_live_categories())
            .order_by(ServiceCategory.sort_order, ServiceCategory.name)
        ).scalars()
    )


def region_slugs_by_category(db: Session) -> dict[uuid.UUID, list[str]]:
    """Which markets offer each category, for the services hub."""
    rows = db.execute(
        select(ServiceRegionAvailability.category_id, Region.slug)
        .join(Region, Region.id == ServiceRegionAvailability.region_id)
        .where(
            ServiceRegionAvailability.is_offered.is_(True),
            Region.is_published.is_(True),
        )
        .order_by(Region.sort_order)
    ).all()

    grouped: dict[uuid.UUID, list[str]] = {}
    for category_id, slug in rows:
        grouped.setdefault(category_id, []).append(slug)
    return grouped


def _resolved(category: ServiceCategory, link: ServiceRegionAvailability) -> dict:
    """Apply a market's overrides to a category."""
    return {
        "id": category.id,
        "slug": category.slug,
        "name": link.name_override or category.name,
        "short_description": (link.short_description_override or category.short_description),
        "long_description": (link.long_description_override or category.long_description),
        "icon_key": category.icon_key,
        "cta_label": category.cta_label,
        "cta_url": category.cta_url,
        "meta_title": category.meta_title,
        "meta_description": category.meta_description,
        # A market can lead with what matters locally. Zero means "no local
        # preference" and falls back to the category's global order, which is
        # the state of a row created by simply switching a market on.
        "sort_order": link.sort_order or category.sort_order,
    }


def services_for_region(db: Session, region: Region) -> list[dict]:
    rows = db.execute(
        select(ServiceCategory, ServiceRegionAvailability)
        .join(
            ServiceRegionAvailability,
            ServiceRegionAvailability.category_id == ServiceCategory.id,
        )
        .where(
            ServiceRegionAvailability.region_id == region.id,
            ServiceRegionAvailability.is_offered.is_(True),
            *_live_categories(),
        )
    ).all()

    resolved = [_resolved(category, link) for category, link in rows]
    return sorted(resolved, key=lambda item: (item["sort_order"], item["name"]))


def service_in_region(
    db: Session, region: Region, service_slug: str
) -> tuple[ServiceCategory, dict] | None:
    row = db.execute(
        select(ServiceCategory, ServiceRegionAvailability)
        .join(
            ServiceRegionAvailability,
            ServiceRegionAvailability.category_id == ServiceCategory.id,
        )
        .where(
            ServiceCategory.slug == service_slug,
            ServiceRegionAvailability.region_id == region.id,
            ServiceRegionAvailability.is_offered.is_(True),
            *_live_categories(),
        )
        .options(selectinload(ServiceCategory.details))
    ).first()

    if row is None:
        return None
    category, link = row
    return category, _resolved(category, link)


def detail_bullets(db: Session, category_id: uuid.UUID) -> list[str]:
    rows = db.execute(
        select(ServiceDetail.text)
        .where(ServiceDetail.category_id == category_id)
        .order_by(ServiceDetail.sort_order)
    ).scalars()
    return list(rows)


def subcategories_for_region(
    db: Session, category_id: uuid.UUID, region_id: uuid.UUID
) -> list[str]:
    """Published subcategories offered in this market.

    Availability inherits from the parent category unless an override row
    exists, so the common case stores nothing and only genuine exceptions —
    CIS being UK-only, GST India-only — need a row.
    """
    overrides = {
        sub_id: offered
        for sub_id, offered in db.execute(
            select(
                SubcategoryRegionAvailability.subcategory_id,
                SubcategoryRegionAvailability.is_offered,
            ).where(SubcategoryRegionAvailability.region_id == region_id)
        ).all()
    }

    rows = db.execute(
        select(ServiceSubcategory)
        .where(
            ServiceSubcategory.category_id == category_id,
            ServiceSubcategory.is_published.is_(True),
            ServiceSubcategory.is_archived.is_(False),
        )
        .order_by(ServiceSubcategory.sort_order, ServiceSubcategory.name)
    ).scalars()

    return [row.name for row in rows if overrides.get(row.id, True)]


#: Separates a service from one of its specific services in a stored answer.
#: Sub-service names are not unique on their own — "VAT Registration" sits
#: under both VAT Services and Business Registration — so the qualified form is
#: what an enquiry stores. The person picking one never reads it: the form
#: groups the options under a service heading and labels them by name alone.
SUB_SERVICE_SEPARATOR = " — "


def merge_sub_services(subcategory_names: list[str], detail_texts: list[str]) -> list[str]:
    """The specific services under a category, as a visitor sees them.

    Two admin-editable lists feed this: `subcategories`, which exists for
    categories that are formally broken down, and `details`, the itemised "what
    this includes" list that every seeded category actually uses. They are the
    same thing to a visitor, so they are one set — deduplicated in case an
    editor enters an item in both, and with a trailing full stop trimmed
    because they read as headings here rather than as sentences in a list.

    The service pages and the enquiry form both render this list, and an
    "Enquire" link only lands on a valid option because both get it from here.
    """
    seen: set[str] = set()
    merged: list[str] = []
    for raw in [*subcategory_names, *detail_texts]:
        name = raw.strip()
        if name.endswith("."):
            name = name[:-1].strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        merged.append(name)
    return merged


def enquiry_catalogue(db: Session) -> list[dict]:
    """Every market, the services offered there, and what sits under each.

    The enquiry form needs the whole tree at once: it narrows the services to
    the chosen market and the specific services to the chosen services, and
    doing that in the browser means no round trip between a person ticking a
    box and seeing what it opened up.

    Built in one pass rather than by calling the per-service helpers in a loop,
    which would be two queries per (service, market) pair.
    """
    regions = published_regions(db)
    if not regions:
        return []

    links = db.execute(
        select(ServiceCategory, ServiceRegionAvailability)
        .join(
            ServiceRegionAvailability,
            ServiceRegionAvailability.category_id == ServiceCategory.id,
        )
        .where(ServiceRegionAvailability.is_offered.is_(True), *_live_categories())
    ).all()

    details: dict[uuid.UUID, list[str]] = {}
    for category_id, text in db.execute(
        select(ServiceDetail.category_id, ServiceDetail.text).order_by(ServiceDetail.sort_order)
    ).all():
        details.setdefault(category_id, []).append(text)

    subcategories: dict[uuid.UUID, list[ServiceSubcategory]] = {}
    for row in db.execute(
        select(ServiceSubcategory)
        .where(
            ServiceSubcategory.is_published.is_(True),
            ServiceSubcategory.is_archived.is_(False),
        )
        .order_by(ServiceSubcategory.sort_order, ServiceSubcategory.name)
    ).scalars():
        subcategories.setdefault(row.category_id, []).append(row)

    # Absence of a row means "inherit the parent category", so the default here
    # matches the default in `subcategories_for_region`.
    overrides = {
        (subcategory_id, region_id): is_offered
        for subcategory_id, region_id, is_offered in db.execute(
            select(
                SubcategoryRegionAvailability.subcategory_id,
                SubcategoryRegionAvailability.region_id,
                SubcategoryRegionAvailability.is_offered,
            )
        ).all()
    }

    by_region: dict[uuid.UUID, list[dict]] = {}
    for category, link in links:
        resolved = _resolved(category, link)
        offered_subcategories = [
            row.name
            for row in subcategories.get(category.id, [])
            if overrides.get((row.id, link.region_id), True)
        ]
        names = merge_sub_services(offered_subcategories, details.get(category.id, []))
        by_region.setdefault(link.region_id, []).append(
            {
                "name": resolved["name"],
                "sort_order": resolved["sort_order"],
                "sub_services": [
                    {
                        "value": f"{resolved['name']}{SUB_SERVICE_SEPARATOR}{name}",
                        "label": name,
                    }
                    for name in names
                ],
            }
        )

    catalogue = []
    for region in regions:
        services = sorted(
            by_region.get(region.id, []), key=lambda item: (item["sort_order"], item["name"])
        )
        catalogue.append(
            {
                "country": region.name,
                "services": [
                    {"name": item["name"], "sub_services": item["sub_services"]}
                    for item in services
                ],
            }
        )
    return catalogue


def other_regions_offering(
    db: Session, category_id: uuid.UUID, exclude_region_id: uuid.UUID
) -> list[Region]:
    return list(
        db.execute(
            select(Region)
            .join(
                ServiceRegionAvailability,
                ServiceRegionAvailability.region_id == Region.id,
            )
            .where(
                ServiceRegionAvailability.category_id == category_id,
                ServiceRegionAvailability.is_offered.is_(True),
                Region.id != exclude_region_id,
                Region.is_published.is_(True),
            )
            .order_by(Region.sort_order)
        ).scalars()
    )
