"""Task schemas — spec Sections 5.3.B and 6.3."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import TaskStatus


class PersonSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None


class TaskBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    title: str
    description: str | None
    status: TaskStatus
    due_date: date | None
    service_category_id: uuid.UUID | None
    service_category_name: str | None = None
    service_subcategory_id: uuid.UUID | None
    completed_note: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ClientTaskOut(TaskBase):
    """What a client sees.

    Deliberately narrower than the staff view: no internal assignment, no
    created-by, no archive flag. Clients are view-only on tasks (Section
    5.3.B), and who inside SmartAWARE is doing the work is not their record.
    """

    completed_by_name: str | None = None


class TaskOut(TaskBase):
    """The staff view."""

    client_ref: str
    client_company_name: str | None
    assigned_manager: PersonSummary | None = None
    created_by: PersonSummary | None = None
    completed_by: PersonSummary | None = None
    is_archived: bool


class TaskCreate(BaseModel):
    client_id: uuid.UUID
    title: str = Field(min_length=3, max_length=255)
    description: str | None = None
    due_date: date | None = None
    status: TaskStatus = TaskStatus.PENDING
    assigned_manager_id: uuid.UUID | None = None
    service_category_id: uuid.UUID | None = None
    service_subcategory_id: uuid.UUID | None = None


class TaskUpdate(BaseModel):
    """Progress updates.

    `status` cannot be set to completed here — completion needs a note and a
    server-recorded timestamp, so it has its own endpoint (Section 6.3).
    """

    title: str | None = Field(default=None, min_length=3, max_length=255)
    description: str | None = None
    due_date: date | None = None
    status: TaskStatus | None = None
    assigned_manager_id: uuid.UUID | None = None
    service_category_id: uuid.UUID | None = None
    service_subcategory_id: uuid.UUID | None = None


class TaskCompleteRequest(BaseModel):
    #: Required by Section 6.3. There is deliberately no date field: the
    #: timestamp is recorded server-side so completion cannot be backdated.
    note: str = Field(min_length=3, max_length=2000)


class TaskCounts(BaseModel):
    total: int
    pending: int
    in_progress: int
    completed: int
    cancelled: int
    overdue: int
