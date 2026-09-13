"""Reading website content.

Public callers only ever see published rows. That filter lives here rather than
in each route so an unpublished testimonial or an unverified qualification
cannot reach the website through a handler that forgot to apply it.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.content import (
    Achievement,
    ContactDetail,
    ContentBlock,
    ContentListItem,
    CoreValue,
    KeyStrength,
    LegalPage,
    Milestone,
    Qualification,
    SocialLink,
    TeamMember,
    Testimonial,
)
from app.models.service import ServiceCategory
from app.services import service_catalog


def _published(model, db: Session, *order):
    stmt = select(model).where(model.is_published.is_(True))
    return list(db.execute(stmt.order_by(*order)).scalars())


def get_block(db: Session, key: str, *, published_only: bool = True) -> ContentBlock | None:
    stmt = select(ContentBlock).where(ContentBlock.key == key)
    if published_only:
        stmt = stmt.where(ContentBlock.is_published.is_(True))
    return db.execute(stmt).scalar_one_or_none()


def get_block_items(db: Session, key: str) -> list[str]:
    rows = db.execute(
        select(ContentListItem.text)
        .where(ContentListItem.block_key == key, ContentListItem.is_published.is_(True))
        .order_by(ContentListItem.sort_order)
    ).scalars()
    return list(rows)


def block_payload(db: Session, key: str) -> dict | None:
    """A block plus its bullet list, shaped for ContentBlockOut."""
    block = get_block(db, key)
    if block is None:
        return None
    return {
        "id": block.id,
        "key": block.key,
        "title": block.title,
        "subtitle": block.subtitle,
        "body": block.body,
        "sort_order": block.sort_order,
        "is_published": block.is_published,
        "items": get_block_items(db, key),
    }


def core_values(db: Session) -> list[CoreValue]:
    return _published(CoreValue, db, CoreValue.sort_order)


def key_strengths(db: Session) -> list[KeyStrength]:
    return _published(KeyStrength, db, KeyStrength.sort_order)


def milestones(db: Session) -> list[Milestone]:
    return _published(Milestone, db, Milestone.sort_order)


def team(db: Session) -> list[TeamMember]:
    return _published(TeamMember, db, TeamMember.sort_order, TeamMember.name)


def qualifications(db: Session) -> list[Qualification]:
    """Published AND verified.

    The content brief states only verified credentials may appear publicly, so
    publishing alone is not enough to put one on the site.
    """
    return list(
        db.execute(
            select(Qualification)
            .where(
                Qualification.is_published.is_(True),
                Qualification.is_verified.is_(True),
            )
            .order_by(Qualification.sort_order)
        ).scalars()
    )


def achievements(db: Session) -> list[Achievement]:
    return _published(Achievement, db, Achievement.sort_order)


def testimonials(db: Session) -> list[Testimonial]:
    return _published(Testimonial, db, Testimonial.sort_order)


def contact_details(db: Session) -> list[ContactDetail]:
    return _published(ContactDetail, db, ContactDetail.sort_order)


def social_links(db: Session) -> list[SocialLink]:
    return _published(SocialLink, db, SocialLink.sort_order)


def legal_pages(db: Session) -> list[LegalPage]:
    return _published(LegalPage, db, LegalPage.title)


def legal_page(db: Session, slug: str) -> LegalPage | None:
    return db.execute(
        select(LegalPage).where(LegalPage.slug == slug, LegalPage.is_published.is_(True))
    ).scalar_one_or_none()


def service_teasers(
    db: Session, limit: int | None = None, region_slug: str | None = None
) -> list[ServiceCategory] | list[dict]:
    """Published, non-archived service categories for the homepage.

    Scoped to a market when one is given, because the homepage links each teaser
    into that market's service page — an unscoped list would offer a card for a
    service that market does not provide, and the link would 404. The market's
    own naming is applied at the same time, so a category renamed for a region
    reads consistently from the homepage onwards.

    An unknown or unpublished slug falls back to the unscoped list rather than
    erroring: the slug reaches us from a cookie the visitor controls, and a
    market can be unpublished at any time.
    """
    if region_slug:
        region = service_catalog.get_region(db, region_slug)
        if region is not None:
            scoped = service_catalog.services_for_region(db, region)
            return scoped[:limit] if limit is not None else scoped

    stmt = (
        select(ServiceCategory)
        .where(
            ServiceCategory.is_published.is_(True),
            ServiceCategory.is_archived.is_(False),
        )
        .order_by(ServiceCategory.sort_order)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.execute(stmt).scalars())
