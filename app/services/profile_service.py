"""Client profile and onboarding.

Both are described by database rows rather than fixed forms: Section 13 leaves
the profile field list (item 3) and the wizard questions (item 2) unconfirmed,
so the shape has to be data SmartAWARE can change.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.client import Client
from app.models.form_schema import FormDefinition, FormField
from app.models.onboarding import OnboardingResponse, WizardQuestion, WizardStep

PROFILE_FORM_KEY = "client_profile"

#: Profile fields backed by real columns on `clients`. Anything else the form
#: defines is stored in `clients.extra`, so SmartAWARE can add a field without
#: a migration — while the fields that are queried, searched and reported on
#: stay proper columns.
CLIENT_COLUMNS = {
    "company_name",
    "owner_name",
    "company_registration_number",
    "registration_date",
    "address_line1",
    "address_line2",
    "city",
    "region_or_county",
    "postcode",
    "country",
    "contact_email",
    "contact_phone",
}

DATE_COLUMNS = {"registration_date"}

MAX_VALUE_LENGTH = 2000


class ProfileError(Exception):
    """Update refused. The message is safe to show the caller."""


def get_form(db: Session) -> FormDefinition | None:
    return db.execute(
        select(FormDefinition)
        .where(FormDefinition.key == PROFILE_FORM_KEY, FormDefinition.is_active.is_(True))
        .options(selectinload(FormDefinition.fields))
    ).scalar_one_or_none()


def active_fields(form: FormDefinition) -> list[FormField]:
    return sorted((f for f in form.fields if f.is_active), key=lambda f: f.sort_order)


def read_values(client: Client, form: FormDefinition) -> dict[str, Any]:
    """Current values for the fields the form defines, from wherever they live."""
    extra = client.extra or {}
    values: dict[str, Any] = {}
    for field in active_fields(form):
        if field.key in CLIENT_COLUMNS:
            value = getattr(client, field.key, None)
            values[field.key] = value.isoformat() if hasattr(value, "isoformat") else value
        else:
            values[field.key] = extra.get(field.key)
    return values


def update_values(
    db: Session, client: Client, form: FormDefinition, submitted: dict[str, Any]
) -> Client:
    """Apply a profile update.

    Only keys the live form defines are accepted. Unknown keys are ignored
    rather than rejected: a stale browser tab holding a removed field should
    still save, and accepting arbitrary keys would let anyone write unbounded
    data into `extra`.
    """
    fields = {f.key: f for f in active_fields(form)}
    extra = dict(client.extra or {})
    missing: list[str] = []

    for key, field in fields.items():
        if key not in submitted:
            continue

        value = submitted[key]
        if isinstance(value, str):
            value = value.strip()
            if len(value) > MAX_VALUE_LENGTH:
                raise ProfileError(f"“{field.label}” is too long.")
        if value == "":
            value = None

        if value is None and field.is_required:
            missing.append(field.label)
            continue

        if key in CLIENT_COLUMNS:
            if key in DATE_COLUMNS and value:
                try:
                    value = datetime.fromisoformat(str(value)).date()
                except ValueError as exc:
                    raise ProfileError(f"“{field.label}” is not a valid date.") from exc
            setattr(client, key, value)
        elif value is None:
            extra.pop(key, None)
        else:
            extra[key] = value

    if missing:
        raise ProfileError(f"Please complete: {', '.join(missing)}.")

    client.extra = extra
    db.flush()
    return client


# --- Onboarding wizard (Section 5.2) ------------------------------------------


def wizard_steps(db: Session) -> list[WizardStep]:
    return list(
        db.execute(
            select(WizardStep)
            .where(WizardStep.is_active.is_(True))
            .options(selectinload(WizardStep.questions))
            .order_by(WizardStep.sort_order)
        ).scalars()
    )


def active_questions(steps: list[WizardStep]) -> dict[str, WizardQuestion]:
    return {
        question.key: question
        for step in steps
        for question in step.questions
        if question.is_active
    }


def read_answers(db: Session, client_id: uuid.UUID) -> dict[str, Any]:
    """Answers keyed by question key rather than id.

    Reordering or rewording a question keeps its answers attached, which a
    positional scheme would lose.
    """
    rows = db.execute(
        select(OnboardingResponse, WizardQuestion.key)
        .join(WizardQuestion, WizardQuestion.id == OnboardingResponse.question_id)
        .where(OnboardingResponse.client_id == client_id)
    ).all()
    return {key: response.value for response, key in rows}


def save_answers(
    db: Session,
    *,
    client: Client,
    submitted: dict[str, Any],
    complete: bool,
) -> Client:
    steps = wizard_steps(db)
    questions = active_questions(steps)

    for key, value in submitted.items():
        question = questions.get(key)
        if question is None:
            # Unknown key: ignored, for the same reason as the profile.
            continue
        if isinstance(value, str) and len(value) > MAX_VALUE_LENGTH:
            raise ProfileError(f"“{question.label}” is too long.")

        existing = db.execute(
            select(OnboardingResponse).where(
                OnboardingResponse.client_id == client.id,
                OnboardingResponse.question_id == question.id,
            )
        ).scalar_one_or_none()

        if existing is None:
            db.add(OnboardingResponse(client_id=client.id, question_id=question.id, value=value))
        else:
            existing.value = value
            existing.answered_at = datetime.now(UTC)

    db.flush()

    if complete:
        answered = read_answers(db, client.id)
        unanswered = [
            question.label
            for key, question in questions.items()
            if question.is_required and answered.get(key) in (None, "", [])
        ]
        if unanswered:
            raise ProfileError(f"Please answer: {', '.join(unanswered)}.")
        client.onboarding_completed_at = datetime.now(UTC)
        db.flush()

    return client
