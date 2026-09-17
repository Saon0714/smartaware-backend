"""Smart AI and FAQ schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FaqEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    answer: str
    category: str | None
    sort_order: int
    is_published: bool
    is_deleted: bool
    deleted_at: datetime | None
    indexed_at: datetime | None
    updated_at: datetime


class FaqEntryWrite(BaseModel):
    question: str = Field(min_length=3)
    answer: str = Field(min_length=1)
    category: str | None = Field(default=None, max_length=128)
    sort_order: int = 0
    is_published: bool = True


class FaqIndexStatus(BaseModel):
    """What the nightly job would do right now."""

    total: int
    indexed: int
    pending: int
    retired: int
    last_indexed_at: datetime | None


class ChatTurn(BaseModel):
    """One turn of the conversation, as the asker's browser holds it.

    History arrives with the question rather than being looked up, because
    there is nothing to look it up in: the server keeps no transcript. It is
    capped and re-cleaned server-side all the same — anything a caller sends is
    a claim, not a record.
    """

    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    history: list[ChatTurn] = Field(
        default_factory=list,
        max_length=12,
        description="Earlier turns, oldest first. Held by the browser, never stored here.",
    )


class AskResponse(BaseModel):
    answer: str
    escalated: bool
    top_similarity: float | None = None
