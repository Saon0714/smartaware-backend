"""Admin content management.

Nine of the content types are structurally identical — an ordered, publishable
list of rows — so they share a typed router factory rather than forty-odd
hand-written endpoints that would drift apart over time. Each still gets its
own path, tag and concrete schemas, so the generated OpenAPI (and therefore the
frontend's types) stays explicit.

Content blocks and legal pages are handled separately: their keys and slugs are
structural, referenced by page templates, so they can be edited but not created
or deleted from the UI.
"""

# NOTE: deliberately no `from __future__ import annotations`.
# The router factory below annotates its request body with the
# `write_schema` variable. Postponed evaluation would turn that into an
# unresolvable ForwardRef, and FastAPI could not build a request model
# from it.

import uuid
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, create_model
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, DbSession, require_permission
from app.core.permissions import Permission
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
from app.schemas.content import (
    AchievementOut,
    AchievementWrite,
    ContactDetailOut,
    ContactDetailWrite,
    ContentBlockOut,
    ContentBlockUpdate,
    ContentListItemCreate,
    ContentListItemOut,
    ContentListItemUpdate,
    CoreValueOut,
    CoreValueWrite,
    KeyStrengthOut,
    KeyStrengthWrite,
    LegalPageOut,
    LegalPageUpdate,
    MilestoneOut,
    MilestoneWrite,
    QualificationOut,
    QualificationWrite,
    ReorderRequest,
    SocialLinkOut,
    SocialLinkWrite,
    TeamMemberOut,
    TeamMemberWrite,
    TestimonialOut,
    TestimonialWrite,
)

#: Every route in this module requires it, so managers are included only when
#: SmartAWARE enables `manager_can_manage_content` (Section 13 item 6).
_content_editor = require_permission(Permission.CONTENT_MANAGE)

router = APIRouter(prefix="/admin/content", tags=["admin-content"])


def make_partial(base: type[BaseModel], name: str) -> type[BaseModel]:
    """A copy of `base` with every field optional, for PATCH bodies.

    Reusing the create schema for PATCH would make a partial edit fail
    validation on the fields it deliberately left out. Deriving the partial
    keeps one source of truth — field names, types and constraints such as
    max_length all follow the original automatically.
    """
    fields: dict[str, Any] = {}
    for field_name, field_info in base.model_fields.items():
        optional_info = deepcopy(field_info)
        optional_info.default = None
        fields[field_name] = (field_info.annotation | None, optional_info)
    return create_model(name, **fields)  # type: ignore[call-overload]


def _get_or_404(db: Session, model: Any, row_id: uuid.UUID) -> Any:
    row = db.get(model, row_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return row


def build_content_router(
    *,
    path: str,
    tag: str,
    model: Any,
    out_schema: type[BaseModel],
    write_schema: type[BaseModel],
    default_order: Callable[[], Any],
) -> APIRouter:
    """A full CRUD + reorder router for one ordered content collection."""
    sub = APIRouter(prefix=path, tags=[tag], dependencies=[require_permission_dep()])
    patch_schema = make_partial(write_schema, f"{write_schema.__name__}Patch")

    @sub.get("", response_model=list[out_schema], name="list")
    def list_rows(db: DbSession) -> Any:
        """Admin listing returns unpublished rows too — that is the point of
        having a draft state."""
        return list(db.execute(select(model).order_by(default_order())).scalars())

    @sub.get("/{row_id}", response_model=out_schema, name="get")
    def get_row(row_id: uuid.UUID, db: DbSession) -> Any:
        return _get_or_404(db, model, row_id)

    @sub.post("", response_model=out_schema, status_code=status.HTTP_201_CREATED, name="create")
    def create_row(payload: write_schema, db: DbSession) -> Any:  # type: ignore[valid-type]
        row = model(**payload.model_dump())
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @sub.patch("/{row_id}", response_model=out_schema, name="update")
    def update_row(row_id: uuid.UUID, payload: patch_schema, db: DbSession) -> Any:  # type: ignore[valid-type]
        row = _get_or_404(db, model, row_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(row, field, value)
        db.commit()
        db.refresh(row)
        return row

    @sub.delete("/{row_id}", status_code=status.HTTP_204_NO_CONTENT, name="delete")
    def delete_row(row_id: uuid.UUID, db: DbSession) -> None:
        db.delete(_get_or_404(db, model, row_id))
        db.commit()

    @sub.post("/reorder", response_model=list[out_schema], name="reorder")
    def reorder(payload: ReorderRequest, db: DbSession) -> Any:
        """Position in the submitted list becomes sort_order."""
        rows = {
            row.id: row
            for row in db.execute(select(model).where(model.id.in_(payload.ids))).scalars()
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
        return list(db.execute(select(model).order_by(default_order())).scalars())

    return sub


def require_permission_dep():
    from fastapi import Depends

    return Depends(_content_editor)


COLLECTIONS = [
    dict(
        path="/core-values",
        tag="admin-core-values",
        model=CoreValue,
        out_schema=CoreValueOut,
        write_schema=CoreValueWrite,
        default_order=lambda: CoreValue.sort_order,
    ),
    dict(
        path="/key-strengths",
        tag="admin-key-strengths",
        model=KeyStrength,
        out_schema=KeyStrengthOut,
        write_schema=KeyStrengthWrite,
        default_order=lambda: KeyStrength.sort_order,
    ),
    dict(
        path="/milestones",
        tag="admin-milestones",
        model=Milestone,
        out_schema=MilestoneOut,
        write_schema=MilestoneWrite,
        default_order=lambda: Milestone.sort_order,
    ),
    dict(
        path="/team",
        tag="admin-team",
        model=TeamMember,
        out_schema=TeamMemberOut,
        write_schema=TeamMemberWrite,
        default_order=lambda: TeamMember.sort_order,
    ),
    dict(
        path="/qualifications",
        tag="admin-qualifications",
        model=Qualification,
        out_schema=QualificationOut,
        write_schema=QualificationWrite,
        default_order=lambda: Qualification.sort_order,
    ),
    dict(
        path="/achievements",
        tag="admin-achievements",
        model=Achievement,
        out_schema=AchievementOut,
        write_schema=AchievementWrite,
        default_order=lambda: Achievement.sort_order,
    ),
    dict(
        path="/testimonials",
        tag="admin-testimonials",
        model=Testimonial,
        out_schema=TestimonialOut,
        write_schema=TestimonialWrite,
        default_order=lambda: Testimonial.sort_order,
    ),
    dict(
        path="/contact-details",
        tag="admin-contact-details",
        model=ContactDetail,
        out_schema=ContactDetailOut,
        write_schema=ContactDetailWrite,
        default_order=lambda: ContactDetail.sort_order,
    ),
    dict(
        path="/social-links",
        tag="admin-social-links",
        model=SocialLink,
        out_schema=SocialLinkOut,
        write_schema=SocialLinkWrite,
        default_order=lambda: SocialLink.sort_order,
    ),
]

for spec in COLLECTIONS:
    router.include_router(build_content_router(**spec))  # type: ignore[arg-type]


# --- Content blocks -----------------------------------------------------------
# Keys are structural: page templates reference them by name. Editable, but not
# creatable or deletable from the UI, since removing one would break a page.

blocks = APIRouter(prefix="/blocks", tags=["admin-blocks"], dependencies=[require_permission_dep()])


def _block_payload(db: Session, block: ContentBlock) -> dict:
    items = db.execute(
        select(ContentListItem)
        .where(ContentListItem.block_key == block.key)
        .order_by(ContentListItem.sort_order)
    ).scalars()
    return {
        "id": block.id,
        "key": block.key,
        "title": block.title,
        "subtitle": block.subtitle,
        "body": block.body,
        "sort_order": block.sort_order,
        "is_published": block.is_published,
        "items": [i.text for i in items],
    }


@blocks.get("", response_model=list[ContentBlockOut], name="list")
def list_blocks(db: DbSession) -> Any:
    rows = db.execute(select(ContentBlock).order_by(ContentBlock.sort_order)).scalars()
    return [_block_payload(db, b) for b in rows]


@blocks.get("/{key}", response_model=ContentBlockOut, name="get")
def get_block(key: str, db: DbSession) -> Any:
    block = db.execute(select(ContentBlock).where(ContentBlock.key == key)).scalar_one_or_none()
    if block is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return _block_payload(db, block)


@blocks.patch("/{key}", response_model=ContentBlockOut, name="update")
def update_block(key: str, payload: ContentBlockUpdate, db: DbSession, user: CurrentUser) -> Any:
    block = db.execute(select(ContentBlock).where(ContentBlock.key == key)).scalar_one_or_none()
    if block is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(block, field, value)
    block.updated_by_id = user.id
    db.commit()
    db.refresh(block)
    return _block_payload(db, block)


router.include_router(blocks)


# --- Bullet lists belonging to blocks -----------------------------------------

items = APIRouter(
    prefix="/list-items", tags=["admin-list-items"], dependencies=[require_permission_dep()]
)


@items.get("", response_model=list[ContentListItemOut], name="list")
def list_items(db: DbSession, block_key: str | None = None) -> Any:
    stmt = select(ContentListItem)
    if block_key:
        stmt = stmt.where(ContentListItem.block_key == block_key)
    return list(
        db.execute(stmt.order_by(ContentListItem.block_key, ContentListItem.sort_order)).scalars()
    )


@items.post(
    "", response_model=ContentListItemOut, status_code=status.HTTP_201_CREATED, name="create"
)
def create_item(payload: ContentListItemCreate, db: DbSession) -> Any:
    row = ContentListItem(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@items.patch("/{row_id}", response_model=ContentListItemOut, name="update")
def update_item(row_id: uuid.UUID, payload: ContentListItemUpdate, db: DbSession) -> Any:
    row = _get_or_404(db, ContentListItem, row_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@items.delete("/{row_id}", status_code=status.HTTP_204_NO_CONTENT, name="delete")
def delete_item(row_id: uuid.UUID, db: DbSession) -> None:
    db.delete(_get_or_404(db, ContentListItem, row_id))
    db.commit()


router.include_router(items)


# --- Legal pages --------------------------------------------------------------
# Slugs are structural and map to public routes, so these are editable but not
# creatable or deletable.

legal = APIRouter(prefix="/legal", tags=["admin-legal"], dependencies=[require_permission_dep()])


@legal.get("", response_model=list[LegalPageOut], name="list")
def list_legal(db: DbSession) -> Any:
    return list(db.execute(select(LegalPage).order_by(LegalPage.title)).scalars())


@legal.get("/{slug}", response_model=LegalPageOut, name="get")
def get_legal(slug: str, db: DbSession) -> Any:
    page = db.execute(select(LegalPage).where(LegalPage.slug == slug)).scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return page


@legal.patch("/{slug}", response_model=LegalPageOut, name="update")
def update_legal(slug: str, payload: LegalPageUpdate, db: DbSession) -> Any:
    page = db.execute(select(LegalPage).where(LegalPage.slug == slug)).scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(page, field, value)
    db.commit()
    db.refresh(page)
    return page


router.include_router(legal)
