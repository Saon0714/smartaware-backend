"""Settings management schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.core.setting_schema import Control
from app.models.enums import SettingValueType


class SettingChoice(BaseModel):
    """One option of a `choice` or `multi_choice` setting."""

    value: str
    label: str


class SettingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: Any
    value_type: SettingValueType
    description: str | None
    group: str | None
    is_editable: bool
    updated_at: datetime
    updated_by_id: uuid.UUID | None

    # Editing metadata, so the Admin Portal renders a suitable control rather
    # than a text box for every value.
    control: Control = "text"
    #: Always present: the API falls back to a readable form of the key, so the
    #: Admin Portal never has to show the stored identifier.
    label: str
    choices: list[SettingChoice] = []
    minimum: float | None = None
    maximum: float | None = None
    hint: str | None = None
    unit: str | None = None
    confirm: str | None = None


class SettingGroupOut(BaseModel):
    group: str
    label: str
    settings: list[SettingOut]


class SettingUpdate(BaseModel):
    value: Any
