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


class ClientServiceOut(BaseModel):
    """A service a client is engaged for, as shown in the admin list."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    #: An archived service still appears on the clients who bought it — the
    #: record of what they take is history, not a live catalogue — but the
    #: admin UI marks it so nobody reads it as still on sale.
    is_archived: bool


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
    #: Every service this client takes, on the one row for that client. The
    #: list must not repeat a client per service — see `list_clients`.
    services: list[ClientServiceOut] = Field(default_factory=list)


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
    #: Replaces the whole set. Omitting it leaves the services untouched;
    #: sending an empty list clears them — the two are different requests, which
    #: is why this is `None` by default rather than an empty list.
    service_ids: list[uuid.UUID] | None = None


class StatusChangeRequest(BaseModel):
    status: ClientStatus
    #: Section 6.2 says status is set at Admin's discretion following a
    #: conversation with the client, so a note explaining why is required —
    #: otherwise nobody can later tell a pause from a termination.
    note: str = Field(min_length=3, max_length=1000)


class ManagerClientsRequest(BaseModel):
    """The full set of clients a manager should be looking after.

    Replaces rather than adds: sending a list without a client they currently
    hold takes it off them. Expressed as the whole set because that is the
    question the screen asks — "who does this manager cover?" — and because two
    admins editing at once then conflict visibly instead of silently merging.
    """

    client_ids: list[uuid.UUID] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=1000)


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


class ClientFiltersOut(BaseModel):
    """The values worth filtering the client list by.

    Countries come from the clients that exist rather than from the markets
    SmartAWARE serves: the column is free text, and offering a country nobody is
    filed under would just be a filter that always returns nothing.
    """

    countries: list[str]
    services: list[ClientServiceOut]
