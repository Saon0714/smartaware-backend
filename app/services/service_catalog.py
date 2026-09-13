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
