"""Public service catalogue.

Region-scoped: a service is only reachable through a market that offers it, so
the URL a visitor lands on always matches the wording and availability they are
shown.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.core.deps import DbSession
from app.schemas.service import (
    RegionalServiceDetail,
    RegionOut,
    RegionServicesOut,
    ServiceHubCategory,
    ServiceHubOut,
)
from app.services import service_catalog as catalog

router = APIRouter(prefix="/public", tags=["public-services"])


@router.get("/regions", response_model=list[RegionOut], summary="Published regions")
def list_regions(db: DbSession) -> list[RegionOut]:
    return [RegionOut.model_validate(r) for r in catalog.published_regions(db)]


@router.get("/services", response_model=ServiceHubOut, summary="Services hub")
def services_hub(db: DbSession) -> ServiceHubOut:
    """Every published category, and the markets that offer each."""
    by_category = catalog.region_slugs_by_category(db)
    categories = [
        ServiceHubCategory(
            **{
                field: getattr(category, field)
                for field in (
                    "id",
                    "slug",
                    "name",
                    "short_description",
                    "icon_key",
                    "sort_order",
                )
            },
            region_slugs=by_category.get(category.id, []),
        )
        for category in catalog.live_categories(db)
    ]
    return ServiceHubOut(
        regions=[RegionOut.model_validate(r) for r in catalog.published_regions(db)],
        categories=categories,
    )


@router.get(
    "/regions/{region_slug}/services",
    response_model=RegionServicesOut,
    summary="Services offered in one market",
)
def region_services(region_slug: str, db: DbSession) -> RegionServicesOut:
    region = catalog.get_region(db, region_slug)
    if region is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Region not found.")
    return RegionServicesOut(
        region=RegionOut.model_validate(region),
        services=catalog.services_for_region(db, region),
    )


@router.get(
    "/regions/{region_slug}/services/{service_slug}",
    response_model=RegionalServiceDetail,
    summary="A service as offered in one market",
)
def region_service_detail(
    region_slug: str, service_slug: str, db: DbSession
) -> RegionalServiceDetail:
    region = catalog.get_region(db, region_slug)
    if region is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Region not found.")

    found = catalog.service_in_region(db, region, service_slug)
    if found is None:
        # Also the response when the service exists but is not offered here.
        # Showing it would contradict the brief's requirement that a market
        # lists a service only once SmartAWARE confirms it.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This service is not available in the selected region.",
        )

    category, resolved = found
    details = catalog.detail_bullets(db, category.id)
    subcategories = catalog.subcategories_for_region(db, category.id, region.id)
    return RegionalServiceDetail(
        **resolved,
        details=details,
        subcategories=subcategories,
        # Merged here rather than in the page, so the list a visitor clicks
        # "Enquire" on and the list the enquiry form offers are the same list.
        sub_services=catalog.merge_sub_services(subcategories, details),
        other_regions=[
            RegionOut.model_validate(r)
            for r in catalog.other_regions_offering(db, category.id, region.id)
        ],
    )
