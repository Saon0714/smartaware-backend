"""Smart AI and FAQ schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ChatRole, ChatSurface


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


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    #: Continues an existing conversation. Issued by the server on first ask.
    session_token: str | None = Field(default=None, max_length=128)


class AskResponse(BaseModel):
    session_token: str
    answer: str
    escalated: bool
    #: Present so the escalation threshold can be tuned against real traffic.
    top_similarity: float | None


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: ChatRole
    content: str
    escalated: bool
    top_similarity: float | None
    created_at: datetime


class ChatSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    surface: ChatSurface
    user_id: uuid.UUID | None
    client_id: uuid.UUID | None
    created_at: datetime
    last_activity_at: datetime | None
    message_count: int = 0


class ChatSessionDetail(ChatSessionOut):
    messages: list[ChatMessageOut] = Field(default_factory=list)
