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
from app.services import service_catalog

ENQUIRY_FORM_KEY = "enquiry"

#: Three field keys the rest of the system reads by name. The field list is
#: otherwise entirely data — these are structural, in the way a column name is:
#: the service pages prefill them, the catalogue narrows them, and an enquiry is
#: listed by what they hold. Renaming one in the Admin Portal would break that
#: wiring, which is why they are named here rather than assumed everywhere.
COUNTRY_FIELD = "country"
SERVICE_FIELD = "service_required"
SUB_SERVICE_FIELD = "sub_services"

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

#: The narrowest of the denormalised columns.
_COLUMN_LIMIT = 255


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
        select(Region.name).where(Region.is_published.is_(True)).order_by(Region.sort_order)
    ).scalars()
    return [*rows, "Other"]


def service_options(db: Session, country: str | None = None) -> list[str]:
    """Choices for the "Services Required" field.

    Sourced from the live taxonomy so the form and the website can never offer
    different services — and from the *market's* taxonomy, because a market can
    rename a service. India lists "VAT / GST Services" where the UK lists "VAT
    Services", and an enquiry sent from India's page names it the way India's
    page does. Reading the raw category name here rejected that enquiry
    outright.

    Without a country, every market's names are offered: the form has not been
    narrowed yet, and refusing a name because the person had not said where
    they are would be the same bug one step earlier.
    """
    markets = service_catalog.enquiry_catalogue(db)
    if country:
        markets = [m for m in markets if m["country"] == country] or markets
    seen: set[str] = set()
    names: list[str] = []
    for market in markets:
        for service in market["services"]:
            if service["name"] not in seen:
                seen.add(service["name"])
                names.append(service["name"])
    return names


def sub_service_options(
    db: Session, country: str | None = None, services: list[str] | None = None
) -> list[str]:
    """Valid answers for the specific-services field, in the same state the form
    would be in: narrowed to the chosen market, then to the chosen services.

    Mirrors what the browser offers rather than re-deriving it, so a submission
    can only be refused for something the person could actually see.
    """
    markets = service_catalog.enquiry_catalogue(db)
    if country:
        markets = [m for m in markets if m["country"] == country] or markets
    wanted = set(services or [])
    values: list[str] = []
    seen: set[str] = set()
    for market in markets:
        for service in market["services"]:
            if wanted and service["name"] not in wanted:
                continue
            for option in service["sub_services"]:
                if option["value"] not in seen:
                    seen.add(option["value"])
                    values.append(option["value"])
    return values


def describe_form(
    db: Session, form: FormDefinition, *, include_inactive: bool = False
) -> dict[str, Any]:
    """The definition as the frontend needs it, with dynamic options filled in.

    Retired fields are left out of the public form — that is what retiring one
    means — but the Admin Portal asks for them. Without that, deactivating a
    field would be a one-way door, and the answers enquiries already hold under
    its key would have nothing left to label them with.
    """
    options = service_options(db)
    countries = country_options(db)
    fields = []
    chosen = (
        sorted(form.fields, key=lambda field: field.sort_order)
        if include_inactive
        else active_fields(form)
    )
    for field in chosen:
        data = {
            "id": field.id,
            "key": field.key,
            "label": field.label,
            "field_type": field.field_type,
            "placeholder": field.placeholder,
            "help_text": field.help_text,
            "is_required": field.is_required,
            "is_active": field.is_active,
            "options": field.options,
            "validation": field.validation,
            "sort_order": field.sort_order,
        }
        # Selects with no stored options draw them from live data, so the form
        # can never offer a service or a market that is not actually served.
        if field.key == SERVICE_FIELD and not field.options:
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

        if isinstance(value, list):
            # A multi-answer field. Every entry is checked, not just the first:
            # anything that reaches the payload is shown to staff and emailed
            # out, so an unchecked entry is an unchecked string in both.
            entries = [str(entry).strip() for entry in value]
            if any(len(entry) > MAX_ANSWER_LENGTH for entry in entries):
                raise EnquiryError(f"“{field.label}” is too long.")
            entries = list(dict.fromkeys(entry for entry in entries if entry))
            if not entries:
                if field.is_required:
                    missing.append(field.label)
                continue
            if field.options:
                unknown = [entry for entry in entries if entry not in field.options]
                if unknown:
                    raise EnquiryError(f"“{unknown[0]}” is not a valid choice for {field.label}.")
            cleaned[field.key] = entries
            continue

        # Only enforced for stored option lists. Services and the specific
        # services under them come from the taxonomy and are checked below.
        if (
            field.options
            and field.key not in (SERVICE_FIELD, SUB_SERVICE_FIELD)
            and isinstance(value, str)
            and value not in field.options
        ):
            raise EnquiryError(f"“{value}” is not a valid choice for {field.label}.")

        cleaned[field.key] = value

    if missing:
        raise EnquiryError(f"Please complete: {', '.join(missing)}.")

    _check_against_catalogue(db, cleaned)
    return cleaned


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(entry) for entry in value]
    return [str(value)] if value else []


def _check_against_catalogue(db: Session, cleaned: dict[str, Any]) -> None:
    """Check the services and specific services against the live taxonomy.

    Checked together and in this order because the second depends on the first:
    what counts as a valid specific service is decided by the market and the
    services chosen, exactly as it is in the form.
    """
    country = cleaned.get(COUNTRY_FIELD)
    country = country if isinstance(country, str) else None

    services = _as_list(cleaned.get(SERVICE_FIELD))
    if services:
        valid = service_options(db, country)
        unknown = [name for name in services if name not in valid]
        if valid and unknown:
            raise EnquiryError(f"“{unknown[0]}” is not one of the services offered.")

    sub_services = _as_list(cleaned.get(SUB_SERVICE_FIELD))
    if sub_services:
        valid = sub_service_options(db, country, services)
        unknown = [name for name in sub_services if name not in valid]
        if valid and unknown:
            raise EnquiryError(f"“{unknown[0]}” is not offered under the services you chose.")


def create_enquiry(db: Session, form: FormDefinition, answers: dict[str, Any]) -> Enquiry:
    cleaned = validate_and_clean(db, form, answers)

    enquiry = Enquiry(form_key=form.key, payload=cleaned)
    for column in DENORMALISED:
        value = cleaned.get(column)
        if isinstance(value, list):
            # These columns exist so the Admin Portal can list an enquiry
            # without opening its payload. A multi-answer field is joined for
            # that purpose only; `payload` keeps the answer as it was given.
            value = ", ".join(str(entry) for entry in value)[:_COLUMN_LIMIT]
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
