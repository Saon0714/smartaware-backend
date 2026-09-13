"""Client management schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import ClientStatus, UserRole


class StaffSummary(BaseModel):
    """A manager or admin, as shown in assignment controls."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: UserRole
    is_active: bool


class ClientSummary(BaseModel):
    """A row in the client list.

    Section 6.2 requires the assigned manager to be visible alongside each
    user, so it is part of the list payload rather than a second lookup.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_ref: str
    company_name: str | None
    owner_name: str | None
    contact_email: EmailStr | None
    country: str | None
    status: ClientStatus
    onboarding_completed_at: datetime | None
    created_at: datetime

    user_id: uuid.UUID
    user_email: EmailStr
    user_is_active: bool
    last_login_at: datetime | None

    assigned_manager: StaffSummary | None = None


class ClientDetail(ClientSummary):
    company_registration_number: str | None
    registration_date: date | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    region_or_county: str | None
    postcode: str | None
    contact_phone: str | None
    status_note: str | None
    extra: dict[str, Any] = Field(default_factory=dict)


class ClientUpdate(BaseModel):
    company_name: str | None = Field(default=None, max_length=255)
    owner_name: str | None = Field(default=None, max_length=255)
    company_registration_number: str | None = Field(default=None, max_length=64)
    registration_date: date | None = None
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=128)
    region_or_county: str | None = Field(default=None, max_length=128)
    postcode: str | None = Field(default=None, max_length=32)
    country: str | None = Field(default=None, max_length=128)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=64)
    extra: dict[str, Any] | None = None


class StatusChangeRequest(BaseModel):
    status: ClientStatus
    #: Section 6.2 says status is set at Admin's discretion following a
    #: conversation with the client, so a note explaining why is required —
    #: otherwise nobody can later tell a pause from a termination.
    note: str = Field(min_length=3, max_length=1000)


class ManagerAssignmentRequest(BaseModel):
    #: Null clears the assignment.
    manager_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=1000)


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_email: EmailStr | None = None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None
    reason: str | None
    created_at: datetime
