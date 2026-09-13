"""Admin management of regions and the service taxonomy.

Everything SmartAWARE needs to add, edit, reorder, publish and remove services
without a developer. Two behaviours are deliberate and worth stating:

  * Deleting a category archives it. Tasks carry a service_category_id, so
    destroying the row would either break the foreign key or orphan the record
    of completed work. Archived categories vanish from the website and from
    new-task pickers while history keeps its reference. A genuinely unused
    category can still be hard-deleted.
  * Availability is a single upsert per (category, region) pair, so the admin
    grid can toggle a cell without needing to know whether a row exists yet.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.deps import DbSession, require_permission
from app.core.permissions import Permission
from app.models.service import (
    Region,
    ServiceCategory,
    ServiceDetail,
    ServiceRegionAvailability,
    ServiceSubcategory,
)
from app.models.task import Task
from app.schemas.content import ReorderRequest
from app.schemas.partial import make_partial
from app.schemas.service import (
    AvailabilityOut,
    AvailabilityWrite,
    CategoryAvailabilityGrid,
    CategoryAvailabilityRow,
    RegionOut,
    RegionWrite,
    ServiceCategoryOut,
    ServiceCategoryWrite,
    ServiceDetailOut,
    ServiceDetailWrite,
    ServiceSubcategoryOut,
    ServiceSubcategoryWrite,
)
from app.services.service_catalog import slugify

RegionPatch = make_partial(RegionWrite)
ServiceCategoryPatch = make_partial(ServiceCategoryWrite)
ServiceSubcategoryPatch = make_partial(ServiceSubcategoryWrite)

_editor = Depends(require_permission(Permission.CONTENT_MANAGE))

router = APIRouter(prefix="/admin", dependencies=[_editor])


def _get_or_404(db, model: Any, row_id: uuid.UUID, label: str) -> Any:
    row = db.get(model, row_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found.")
    return row


# --- Regions ------------------------------------------------------------------

regions = APIRouter(prefix="/regions", tags=["admin-regions"])


@regions.get("", response_model=list[RegionOut], name="list")
def list_regions(db: DbSession) -> Any:
    return list(db.execute(select(Region).order_by(Region.sort_order)).scalars())


@regions.post("", response_model=RegionOut, status_code=status.HTTP_201_CREATED, name="create")
def create_region(payload: RegionWrite, db: DbSession) -> Any:
    if db.execute(select(Region).where(Region.slug == payload.slug)).scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A region with that slug exists."
        )
    row = Region(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@regions.patch("/{region_id}", response_model=RegionOut, name="update")
def update_region(region_id: uuid.UUID, payload: RegionPatch, db: DbSession) -> Any:
    row = _get_or_404(db, Region, region_id, "Region")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@regions.delete("/{region_id}", status_code=status.HTTP_204_NO_CONTENT, name="delete")
def delete_region(region_id: uuid.UUID, db: DbSession) -> None:
    row = _get_or_404(db, Region, region_id, "Region")
    db.delete(row)
    db.commit()


router.include_router(regions)


# --- Service categories --------------------------------------------------------

categories = APIRouter(prefix="/services", tags=["admin-services"])


@categories.get("", response_model=list[ServiceCategoryOut], name="list")
def list_categories(
    db: DbSession,
    include_archived: bool = Query(default=False),
) -> Any:
    stmt = select(ServiceCategory).options(
        selectinload(ServiceCategory.details),
        selectinload(ServiceCategory.subcategories),
    )
    if not include_archived:
        stmt = stmt.where(ServiceCategory.is_archived.is_(False))
    return list(db.execute(stmt.order_by(ServiceCategory.sort_order)).scalars())


@categories.get("/{category_id}", response_model=ServiceCategoryOut, name="get")
def get_category(category_id: uuid.UUID, db: DbSession) -> Any:
    return _get_or_404(db, ServiceCategory, category_id, "Service")


@categories.post(
    "", response_model=ServiceCategoryOut, status_code=status.HTTP_201_CREATED, name="create"
)
def create_category(payload: ServiceCategoryWrite, db: DbSession) -> Any:
    data = payload.model_dump()
    data["slug"] = data.get("slug") or slugify(payload.name)
    if db.execute(
        select(ServiceCategory).where(ServiceCategory.slug == data["slug"])
    ).scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A service with that slug exists."
        )
    row = ServiceCategory(**data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@categories.patch("/{category_id}", response_model=ServiceCategoryOut, name="update")
def update_category(category_id: uuid.UUID, payload: ServiceCategoryPatch, db: DbSession) -> Any:
    row = _get_or_404(db, ServiceCategory, category_id, "Service")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "slug" and not value:
            continue
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@categories.delete("/{category_id}", response_model=ServiceCategoryOut, name="delete")
def archive_category(
    category_id: uuid.UUID,
    db: DbSession,
    hard: bool = Query(
        default=False,
        description="Permanently delete. Refused if any task references it.",
    ),
) -> Any:
    """Archive by default; hard-delete only when nothing references it."""
    row = _get_or_404(db, ServiceCategory, category_id, "Service")

    if hard:
        referencing = db.execute(
            select(func.count()).select_from(Task).where(Task.service_category_id == category_id)
        ).scalar_one()
        if referencing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"{referencing} task(s) reference this service. "
                    "Archive it instead so their history stays intact."
                ),
            )
        db.delete(row)
        db.commit()
        return ServiceCategoryOut(
            id=category_id,
            slug=row.slug,
            name=row.name,
            short_description=None,
            icon_key=None,
            sort_order=0,
            long_description=None,
            cta_label=None,
            cta_url=None,
            is_published=False,
            is_archived=True,
            meta_title=None,
            meta_description=None,
        )

    row.is_archived = True
    row.is_published = False
    db.commit()
    db.refresh(row)
    return row


@categories.post("/{category_id}/restore", response_model=ServiceCategoryOut, name="restore")
def restore_category(category_id: uuid.UUID, db: DbSession) -> Any:
    row = _get_or_404(db, ServiceCategory, category_id, "Service")
    row.is_archived = False
    db.commit()
    db.refresh(row)
    return row


@categories.post("/reorder", response_model=list[ServiceCategoryOut], name="reorder")
def reorder_categories(payload: ReorderRequest, db: DbSession) -> Any:
    rows = {
        r.id: r
        for r in db.execute(
            select(ServiceCategory).where(ServiceCategory.id.in_(payload.ids))
        ).scalars()
    }
    missing = [str(i) for i in payload.ids if i not in rows]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown ids: {', '.join(missing)}",
        )
    for position, row_id in enumerate(payload.ids, start=1):
        rows[row_id].sort_order = position
    db.commit()
    return list(
        db.execute(
            select(ServiceCategory)
            .where(ServiceCategory.is_archived.is_(False))
            .order_by(ServiceCategory.sort_order)
        ).scalars()
    )


# --- Detail bullets ------------------------------------------------------------


@categories.get(
    "/{category_id}/details", response_model=list[ServiceDetailOut], name="list_details"
)
def list_details(category_id: uuid.UUID, db: DbSession) -> Any:
    return list(
        db.execute(
            select(ServiceDetail)
            .where(ServiceDetail.category_id == category_id)
            .order_by(ServiceDetail.sort_order)
        ).scalars()
    )


@categories.post(
    "/{category_id}/details",
    response_model=ServiceDetailOut,
    status_code=status.HTTP_201_CREATED,
    name="create_detail",
)
def create_detail(category_id: uuid.UUID, payload: ServiceDetailWrite, db: DbSession) -> Any:
    _get_or_404(db, ServiceCategory, category_id, "Service")
    row = ServiceDetail(category_id=category_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@categories.delete(
    "/details/{detail_id}", status_code=status.HTTP_204_NO_CONTENT, name="delete_detail"
)
def delete_detail(detail_id: uuid.UUID, db: DbSession) -> None:
    db.delete(_get_or_404(db, ServiceDetail, detail_id, "Detail"))
    db.commit()


# --- Subcategories -------------------------------------------------------------


@categories.get(
    "/{category_id}/subcategories",
    response_model=list[ServiceSubcategoryOut],
    name="list_subcategories",
)
def list_subcategories(category_id: uuid.UUID, db: DbSession) -> Any:
    return list(
        db.execute(
            select(ServiceSubcategory)
            .where(
                ServiceSubcategory.category_id == category_id,
                ServiceSubcategory.is_archived.is_(False),
            )
            .order_by(ServiceSubcategory.sort_order)
        ).scalars()
    )


@categories.post(
    "/{category_id}/subcategories",
    response_model=ServiceSubcategoryOut,
    status_code=status.HTTP_201_CREATED,
    name="create_subcategory",
)
def create_subcategory(
    category_id: uuid.UUID, payload: ServiceSubcategoryWrite, db: DbSession
) -> Any:
    _get_or_404(db, ServiceCategory, category_id, "Service")
    data = payload.model_dump()
    data["slug"] = data.get("slug") or slugify(payload.name)
    row = ServiceSubcategory(category_id=category_id, **data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@categories.patch(
    "/subcategories/{subcategory_id}",
    response_model=ServiceSubcategoryOut,
    name="update_subcategory",
)
def update_subcategory(
    subcategory_id: uuid.UUID, payload: ServiceSubcategoryPatch, db: DbSession
) -> Any:
    row = _get_or_404(db, ServiceSubcategory, subcategory_id, "Subcategory")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "slug" and not value:
            continue
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@categories.delete(
    "/subcategories/{subcategory_id}",
    response_model=ServiceSubcategoryOut,
    name="archive_subcategory",
)
def archive_subcategory(subcategory_id: uuid.UUID, db: DbSession) -> Any:
    """Archived, not deleted — tasks reference subcategories too."""
    row = _get_or_404(db, ServiceSubcategory, subcategory_id, "Subcategory")
    row.is_archived = True
    row.is_published = False
    db.commit()
    db.refresh(row)
    return row


# --- Region availability -------------------------------------------------------


@categories.get(
    "/{category_id}/availability",
    response_model=CategoryAvailabilityGrid,
    name="availability",
)
def category_availability(category_id: uuid.UUID, db: DbSession) -> Any:
    """One row per region, including markets with no row yet.

    The grid always shows every region so an editor can see what is switched
    off, not merely what happens to have been configured.
    """
    category = _get_or_404(db, ServiceCategory, category_id, "Service")
    links = {
        link.region_id: link
        for link in db.execute(
            select(ServiceRegionAvailability).where(
                ServiceRegionAvailability.category_id == category_id
            )
        ).scalars()
    }
    all_regions = db.execute(select(Region).order_by(Region.sort_order)).scalars()

    return CategoryAvailabilityGrid(
        category_id=category.id,
        category_slug=category.slug,
        category_name=category.name,
        regions=[
            CategoryAvailabilityRow(
                region_id=region.id,
                region_slug=region.slug,
                region_name=region.name,
                is_offered=links[region.id].is_offered if region.id in links else False,
                name_override=links[region.id].name_override if region.id in links else None,
                short_description_override=(
                    links[region.id].short_description_override if region.id in links else None
                ),
                sort_order=links[region.id].sort_order if region.id in links else 0,
            )
            for region in all_regions
        ],
    )


@categories.put(
    "/{category_id}/availability/{region_id}",
    response_model=AvailabilityOut,
    name="set_availability",
)
def set_availability(
    category_id: uuid.UUID,
    region_id: uuid.UUID,
    payload: AvailabilityWrite,
    db: DbSession,
) -> Any:
    """Upsert, so toggling a grid cell works whether or not a row exists."""
    _get_or_404(db, ServiceCategory, category_id, "Service")
    _get_or_404(db, Region, region_id, "Region")

    link = db.execute(
        select(ServiceRegionAvailability).where(
            ServiceRegionAvailability.category_id == category_id,
            ServiceRegionAvailability.region_id == region_id,
        )
    ).scalar_one_or_none()

    if link is None:
        link = ServiceRegionAvailability(category_id=category_id, region_id=region_id)
        db.add(link)

    for field, value in payload.model_dump().items():
        setattr(link, field, value)

    db.commit()
    db.refresh(link)
    return link


router.include_router(categories)
