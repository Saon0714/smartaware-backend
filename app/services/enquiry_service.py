"""Enquiry submission.

The form's fields are rows, so validation is driven by the live definition
rather than a fixed schema. That is what lets SmartAWARE add or remove a field
from the Admin Portal without a deploy — and it means the server must never
assume a particular field exists.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.enquiry import Enquiry
from app.models.enums import FormFieldType
from app.models.form_schema import FormDefinition, FormField
from app.models.service import ServiceCategory

ENQUIRY_FORM_KEY = "enquiry"

#: Columns kept alongside the JSON payload so the Admin Portal can list and
#: search without unpacking JSON. Conveniences only — `payload` stays complete
#: even after the field list changes.
DENORMALISED = (
    "name",
    "email",
    "phone",
    "country",
    "company_name",
    "service_required",
)

MAX_ANSWER_LENGTH = 5000


class EnquiryError(Exception):
    """Submission rejected. The message is safe to show the submitter."""


def get_form(db: Session, key: str = ENQUIRY_FORM_KEY) -> FormDefinition | None:
    return db.execute(
        select(FormDefinition)
        .where(FormDefinition.key == key, FormDefinition.is_active.is_(True))
        .options(selectinload(FormDefinition.fields))
    ).scalar_one_or_none()


def active_fields(form: FormDefinition) -> list[FormField]:
    return sorted(
        (field for field in form.fields if field.is_active),
        key=lambda field: field.sort_order,
    )


def country_options(db: Session) -> list[str]:
    """Choices for a country field.

    Sourced from the markets SmartAWARE actually serves, plus an escape hatch —
    the field rendered as an empty dropdown before this, because only
    `service_required` was being given options, which made it impossible to
    complete.
    """
    from app.models.service import Region

    rows = db.execute(
        select(Region.name)
        .where(Region.is_published.is_(True))
        .order_by(Region.sort_order)
    ).scalars()
    return [*rows, "Other"]


def service_options(db: Session) -> list[str]:
    """Choices for the "Service Required" field.

    Sourced from the live taxonomy so the form and the website can never offer
    different services.
    """
    rows = db.execute(
        select(ServiceCategory.name)
        .where(
            ServiceCategory.is_published.is_(True),
            ServiceCategory.is_archived.is_(False),
        )
        .order_by(ServiceCategory.sort_order)
    ).scalars()
    return list(rows)


def describe_form(db: Session, form: FormDefinition) -> dict[str, Any]:
    """The definition as the frontend needs it, with dynamic options filled in."""
    options = service_options(db)
    countries = country_options(db)
    fields = []
    for field in active_fields(form):
        data = {
            "id": field.id,
            "key": field.key,
            "label": field.label,
            "field_type": field.field_type,
            "placeholder": field.placeholder,
            "help_text": field.help_text,
            "is_required": field.is_required,
            "options": field.options,
            "validation": field.validation,
            "sort_order": field.sort_order,
        }
        # Selects with no stored options draw them from live data, so the form
        # can never offer a service or a market that is not actually served.
        if field.key == "service_required" and not field.options:
            data["options"] = options
        elif field.field_type is FormFieldType.COUNTRY and not field.options:
            data["options"] = countries
        fields.append(data)
    return {
        "key": form.key,
        "name": form.name,
        "description": form.description,
        "fields": fields,
    }


def validate_and_clean(
    db: Session, form: FormDefinition, answers: dict[str, Any]
) -> dict[str, Any]:
    """Check a submission against the live field definition.

    Unknown keys are dropped rather than rejected: a stale browser tab holding
    a removed field should not fail, and accepting arbitrary keys would let
    anyone write unbounded data into the payload column.
    """
    fields = active_fields(form)
    cleaned: dict[str, Any] = {}
    missing: list[str] = []

    for field in fields:
        raw = answers.get(field.key)
        value = raw.strip() if isinstance(raw, str) else raw

        if value in (None, "", []):
            if field.is_required:
                missing.append(field.label)
            continue

        if isinstance(value, str) and len(value) > MAX_ANSWER_LENGTH:
            raise EnquiryError(f"“{field.label}” is too long.")

        # Only enforced for stored option lists. Service names come from the
        # taxonomy and are checked separately below.
        if (
            field.options
            and field.key != "service_required"
            and isinstance(value, str)
            and value not in field.options
        ):
            raise EnquiryError(f"“{value}” is not a valid choice for {field.label}.")

        cleaned[field.key] = value

    if missing:
        raise EnquiryError(f"Please complete: {', '.join(missing)}.")

    if "service_required" in cleaned:
        valid = service_options(db)
        if valid and cleaned["service_required"] not in valid:
            raise EnquiryError("Please choose a service from the list.")

    return cleaned


def create_enquiry(db: Session, form: FormDefinition, answers: dict[str, Any]) -> Enquiry:
    cleaned = validate_and_clean(db, form, answers)

    enquiry = Enquiry(form_key=form.key, payload=cleaned)
    for column in DENORMALISED:
        value = cleaned.get(column)
        setattr(enquiry, column, value if isinstance(value, str) else None)

    db.add(enquiry)
    db.flush()
    return enquiry


def summarise(form: FormDefinition, enquiry: Enquiry) -> str:
    """A readable summary for the notification email."""
    labels = {field.key: field.label for field in active_fields(form)}
    lines = []
    for key, value in enquiry.payload.items():
        rendered = ", ".join(value) if isinstance(value, list) else value
        lines.append(f"{labels.get(key, key)}: {rendered}")
    return "\n".join(lines)
