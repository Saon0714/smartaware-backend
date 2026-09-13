"""Admin: website enquiries and the form's field definition."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.core.deps import DbSession, require_permission
from app.core.permissions import Permission
from app.models.enquiry import Enquiry
from app.models.form_schema import FormDefinition, FormField
from app.schemas.enquiry import (
    EnquiryOut,
    EnquiryUpdate,
    FormDefinitionOut,
    FormFieldOut,
    FormFieldWrite,
)
from app.schemas.partial import make_partial
from app.services import enquiry_service

FormFieldPatch = make_partial(FormFieldWrite)

router = APIRouter(prefix="/admin", tags=["admin-enquiries"])

_viewer = Depends(require_permission(Permission.ENQUIRY_VIEW))
_editor = Depends(require_permission(Permission.CONTENT_MANAGE))


@router.get("/enquiries", response_model=list[EnquiryOut], dependencies=[_viewer], name="list")
def list_enquiries(
    db: DbSession,
    handled: Annotated[bool | None, Query()] = None,
) -> Any:
    stmt = select(Enquiry).order_by(Enquiry.created_at.desc())
    if handled is not None:
        stmt = stmt.where(Enquiry.is_handled.is_(handled))
    return list(db.execute(stmt).scalars())


@router.get(
    "/enquiries/{enquiry_id}",
    response_model=EnquiryOut,
    dependencies=[_viewer],
    name="get",
)
def get_enquiry(enquiry_id: uuid.UUID, db: DbSession) -> Any:
    enquiry = db.get(Enquiry, enquiry_id)
    if enquiry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return enquiry


@router.patch(
    "/enquiries/{enquiry_id}",
    response_model=EnquiryOut,
    dependencies=[_viewer],
    name="update",
)
def update_enquiry(enquiry_id: uuid.UUID, payload: EnquiryUpdate, db: DbSession) -> Any:
    enquiry = db.get(Enquiry, enquiry_id)
    if enquiry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(enquiry, field, value)
    db.commit()
    db.refresh(enquiry)
    return enquiry


# --- Form field definition ------------------------------------------------------
# Section 13 item 1: the final field list is unconfirmed, so it is editable here
# rather than fixed in code.


@router.get(
    "/forms/{form_key}",
    response_model=FormDefinitionOut,
    dependencies=[_editor],
    name="get_form",
)
def get_form(form_key: str, db: DbSession) -> Any:
    form = enquiry_service.get_form(db, form_key)
    if form is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found.")
    return enquiry_service.describe_form(db, form)


def _form_or_404(db, form_key: str) -> FormDefinition:
    form = db.execute(
        select(FormDefinition).where(FormDefinition.key == form_key)
    ).scalar_one_or_none()
    if form is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found.")
    return form


@router.post(
    "/forms/{form_key}/fields",
    response_model=FormFieldOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_editor],
    name="create_field",
)
def create_field(form_key: str, payload: FormFieldWrite, db: DbSession) -> Any:
    form = _form_or_404(db, form_key)
    existing = db.execute(
        select(FormField).where(FormField.form_id == form.id, FormField.key == payload.key)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A field with that key already exists on this form.",
        )
    field = FormField(form_id=form.id, **payload.model_dump())
    db.add(field)
    db.commit()
    db.refresh(field)
    return field


@router.patch(
    "/forms/fields/{field_id}",
    response_model=FormFieldOut,
    dependencies=[_editor],
    name="update_field",
)
def update_field(field_id: uuid.UUID, payload: FormFieldPatch, db: DbSession) -> Any:
    field = db.get(FormField, field_id)
    if field is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    for name, value in payload.model_dump(exclude_unset=True).items():
        setattr(field, name, value)
    db.commit()
    db.refresh(field)
    return field


@router.delete(
    "/forms/fields/{field_id}",
    response_model=FormFieldOut,
    dependencies=[_editor],
    name="deactivate_field",
)
def deactivate_field(field_id: uuid.UUID, db: DbSession) -> Any:
    """Deactivated rather than deleted.

    Past enquiries store the answer under this key, and removing the row would
    leave those submissions with an unlabelled value.
    """
    field = db.get(FormField, field_id)
    if field is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    field.is_active = False
    db.commit()
    db.refresh(field)
    return field
