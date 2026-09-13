"""Profile, onboarding wizard and notes — spec Sections 5.2, 5.3.A and 5.3.G."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.enquiry import FormFieldOut


class ProfileOut(BaseModel):
    """The form to render, and what is currently stored in it.

    Fields come from the database (Section 13 item 3 leaves the final list
    unconfirmed), so the frontend renders whatever it is given rather than
    knowing any field by name.
    """

    fields: list[FormFieldOut]
    values: dict[str, Any]
    client_ref: str
    status: str
    onboarding_completed_at: datetime | None


class ProfileUpdate(BaseModel):
    values: dict[str, Any]


class WizardQuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    label: str
    field_type: str
    help_text: str | None
    is_required: bool
    options: list[Any] | None
    sort_order: int


class WizardStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    title: str
    description: str | None
    sort_order: int
    questions: list[WizardQuestionOut]


class OnboardingOut(BaseModel):
    steps: list[WizardStepOut]
    #: Keyed by question key, so a reordered wizard keeps its answers.
    answers: dict[str, Any]
    completed_at: datetime | None


class OnboardingAnswers(BaseModel):
    answers: dict[str, Any]
    #: Save progress without finishing, so a long wizard can be left and resumed.
    complete: bool = False


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    title: str | None
    content: str
    created_at: datetime
    updated_at: datetime
    author_name: str | None = None


class StaffNoteOut(NoteOut):
    is_visible_to_client: bool
    author_email: EmailStr | None = None
    client_ref: str
    client_company_name: str | None


class NoteWrite(BaseModel):
    client_id: uuid.UUID
    title: str | None = Field(default=None, max_length=255)
    content: str = Field(min_length=1)
    #: Drafts exist so a note can be prepared before the client sees it.
    is_visible_to_client: bool = True


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    content: str | None = Field(default=None, min_length=1)
    is_visible_to_client: bool | None = None


class WizardStepWrite(BaseModel):
    key: str = Field(max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(max_length=255)
    description: str | None = None
    sort_order: int = 0
    is_active: bool = True


class WizardQuestionWrite(BaseModel):
    key: str = Field(max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    field_type: str
    help_text: str | None = None
    is_required: bool = False
    options: list[Any] | None = None
    sort_order: int = 0
    is_active: bool = True
