"""Public website content.

Unauthenticated. Every page on the marketing site is assembled from these
endpoints, so SmartAWARE can change any of it from the Admin Portal without a
deploy.

Each page gets one aggregated endpoint rather than a dozen granular ones: the
About page alone draws on eleven tables, and fetching those separately would
mean eleven round trips before the page could render.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.core.deps import DbSession
from app.schemas.content import (
    AboutPageOut,
    ContactPageOut,
    ContentBlockOut,
    HomePageOut,
    LegalPageOut,
    LegalPageSummary,
)
from app.services import content_service as content

router = APIRouter(prefix="/public", tags=["public-content"])


@router.get("/home", response_model=HomePageOut, summary="Homepage content")
def home_page(
    db: DbSession,
    service_limit: Annotated[int, Query(ge=1, le=24)] = 6,
) -> HomePageOut:
    return HomePageOut(
        hero=content.block_payload(db, "home_hero"),
        key_strengths=content.key_strengths(db),
        services=content.service_teasers(db, limit=service_limit),
        achievements=content.achievements(db),
        testimonials=content.testimonials(db),
    )


@router.get("/about", response_model=AboutPageOut, summary="About Us content")
def about_page(db: DbSession) -> AboutPageOut:
    return AboutPageOut(
        intro=content.block_payload(db, "about_intro"),
        presence=content.block_payload(db, "our_presence_today"),
        vision=content.block_payload(db, "vision"),
        mission=content.block_payload(db, "mission"),
        data_protection=content.block_payload(db, "data_protection"),
        why_choose_us=content.block_payload(db, "why_choose_us"),
        why_choose_us_closing=content.block_payload(db, "why_choose_us_closing"),
        core_values=content.core_values(db),
        key_strengths=content.key_strengths(db),
        milestones=content.milestones(db),
        team=content.team(db),
        qualifications=content.qualifications(db),
        achievements=content.achievements(db),
        testimonials=content.testimonials(db),
    )


@router.get("/contact", response_model=ContactPageOut, summary="Contact details")
def contact_page(db: DbSession) -> ContactPageOut:
    return ContactPageOut(
        details=content.contact_details(db),
        social_links=content.social_links(db),
    )


@router.get(
    "/content/{key}",
    response_model=ContentBlockOut,
    summary="A single content block",
)
def content_block(key: str, db: DbSession) -> ContentBlockOut:
    payload = content.block_payload(db, key)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found.")
    return ContentBlockOut.model_validate(payload)


@router.get(
    "/legal",
    response_model=list[LegalPageSummary],
    summary="Published legal pages",
)
def list_legal_pages(db: DbSession) -> list[LegalPageSummary]:
    """Drives the footer, so unpublished placeholders never appear as links."""
    return [LegalPageSummary.model_validate(p) for p in content.legal_pages(db)]


@router.get("/legal/{slug}", response_model=LegalPageOut, summary="A legal page")
def legal_page(slug: str, db: DbSession) -> LegalPageOut:
    page = content.legal_page(db, slug)
    if page is None:
        # Unpublished pages are indistinguishable from missing ones. A draft
        # privacy policy should not be readable by guessing its slug.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")
    return LegalPageOut.model_validate(page)
