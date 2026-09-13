"""Enquiry form schemas.

The field list is admin-editable (spec Section 3.2, Section 13 item 1), so the
form is described by data the frontend renders rather than a fixed shape.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import FormFieldType


class FormFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    label: str
    field_type: FormFieldType
    placeholder: str | None
    help_text: str | None
    is_required: bool
    options: list[Any] | None
    validation: dict[str, Any] | None
    sort_order: int


class FormDefinitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    description: str | None
    fields: list[FormFieldOut]


class FormFieldWrite(BaseModel):
    key: str = Field(max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(max_length=255)
    field_type: FormFieldType
    placeholder: str | None = Field(default=None, max_length=255)
    help_text: str | None = None
    is_required: bool = False
    options: list[Any] | None = None
    validation: dict[str, Any] | None = None
    sort_order: int = 0
    is_active: bool = True


class EnquiryCreate(BaseModel):
    """A submission.

    Answers arrive as a free-form mapping because the field list is data. The
    server validates it against the live definition rather than trusting a
    fixed shape.
    """

    answers: dict[str, Any]
    #: Anti-spam honeypot. Real browsers leave it empty because it is hidden;
    #: naive bots fill every field they find.
    website: str | None = Field(default=None, description="Leave empty.")


class EnquiryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    form_key: str
    payload: dict[str, Any]
    name: str | None
    email: str | None
    phone: str | None
    country: str | None
    company_name: str | None
    service_required: str | None
    is_handled: bool
    internal_note: str | None
    created_at: datetime


class EnquiryUpdate(BaseModel):
    is_handled: bool | None = None
    internal_note: str | None = None


class EnquiryAccepted(BaseModel):
    id: uuid.UUID
    message: str
