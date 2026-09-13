"""Tax Wizard / onboarding engine (spec Section 5.2).

The actual questions are Section 13 item 2 and still unconfirmed, so the wizard
is built as an engine over ordered rows rather than a coded sequence of screens.
Replacing the question set is data entry.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import FormFieldType
from app.models.user import _enum


class WizardStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wizard_steps"

    key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    questions: Mapped[list[WizardQuestion]] = relationship(
        "WizardQuestion",
        back_populates="step",
        cascade="all, delete-orphan",
        order_by="WizardQuestion.sort_order",
    )


class WizardQuestion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wizard_questions"
    __table_args__ = (UniqueConstraint("step_id", "key", name="uq_wizard_question_key"),)

    step_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("wizard_steps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    field_type: Mapped[FormFieldType] = mapped_column(
        _enum(FormFieldType, "form_field_type"), nullable=False
    )
    help_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    options: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    step: Mapped[WizardStep] = relationship("WizardStep", back_populates="questions")


class OnboardingResponse(UUIDPrimaryKeyMixin, Base):
    """One client's answer to one question.

    Row-per-answer rather than a JSON blob per client, so answers stay
    queryable and a question's history survives the question being reworded.
    """

    __tablename__ = "onboarding_responses"
    __table_args__ = (UniqueConstraint("client_id", "question_id", name="uq_onboarding_response"),)

    client_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("wizard_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
