"""Idempotent seed runner.

Safe to run repeatedly: rows are matched on their natural key and inserted only
when missing. Existing rows are left alone, so re-seeding never overwrites an
edit SmartAWARE has made through the Admin Portal — which is the whole point of
the content being database-driven.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.content import (
    ContactDetail,
    ContentBlock,
    ContentListItem,
    CoreValue,
    KeyStrength,
    LegalPage,
    Milestone,
)
from app.models.form_schema import FormDefinition, FormField
from app.models.onboarding import WizardQuestion, WizardStep
from app.models.service import (
    Region,
    ServiceCategory,
    ServiceDetail,
    ServiceRegionAvailability,
    ServiceSubcategory,
)
from app.models.setting import Setting
from app.seeds.content_seed import (
    CONTACT_DETAILS,
    CONTENT_BLOCKS,
    CONTENT_LIST_ITEMS,
    CORE_VALUES,
    KEY_STRENGTHS,
    LEGAL_PAGES,
    MILESTONES,
)
from app.seeds.forms_seed import FORM_DEFINITIONS
from app.seeds.services_seed import (
    REGION_NAME_OVERRIDES,
    REGION_SERVICES,
    REGIONS,
    SERVICE_CATEGORIES,
)
from app.seeds.settings_seed import SETTINGS_DEFAULTS
from app.seeds.wizard_seed import WIZARD_STEPS


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def _exists(db: Session, model, **filters) -> bool:
    return db.execute(select(model).filter_by(**filters)).scalar_one_or_none() is not None


def seed_settings(db: Session) -> int:
    created = 0
    for row in SETTINGS_DEFAULTS:
        if _exists(db, Setting, key=row["key"]):
            continue
        db.add(Setting(**row))
        created += 1
    return created


def seed_services(db: Session) -> dict[str, int]:
    counts = {"regions": 0, "categories": 0, "subcategories": 0, "details": 0, "availability": 0}

    for row in REGIONS:
        if _exists(db, Region, slug=row["slug"]):
            continue
        db.add(Region(**row))
        counts["regions"] += 1
    db.flush()

    for order, cat in enumerate(SERVICE_CATEGORIES, start=1):
        category = db.execute(
            select(ServiceCategory).where(ServiceCategory.slug == cat["slug"])
        ).scalar_one_or_none()
        if category is None:
            category = ServiceCategory(
                slug=cat["slug"],
                name=cat["name"],
                short_description=cat["short_description"],
                icon_key=cat.get("icon_key"),
                sort_order=order,
                meta_title=f"{cat['name']} | SmartAWARE",
                meta_description=cat["short_description"],
            )
            db.add(category)
            db.flush()
            counts["categories"] += 1

        for i, text in enumerate(cat["details"], start=1):
            if not _exists(db, ServiceDetail, category_id=category.id, text=text):
                db.add(ServiceDetail(category_id=category.id, text=text, sort_order=i))
                counts["details"] += 1

        for i, name in enumerate(cat["subcategories"], start=1):
            slug = slugify(name)
            if not _exists(db, ServiceSubcategory, category_id=category.id, slug=slug):
                db.add(
                    ServiceSubcategory(
                        category_id=category.id,
                        slug=slug,
                        name=name,
                        sort_order=i,
                    )
                )
                counts["subcategories"] += 1
    db.flush()

    regions = {r.slug: r for r in db.execute(select(Region)).scalars()}
    categories = {c.slug: c for c in db.execute(select(ServiceCategory)).scalars()}

    for region_slug, offered in REGION_SERVICES.items():
        region = regions.get(region_slug)
        if region is None:
            continue
        for i, cat_slug in enumerate(offered, start=1):
            category = categories.get(cat_slug)
            if category is None:
                continue
            if _exists(
                db,
                ServiceRegionAvailability,
                category_id=category.id,
                region_id=region.id,
            ):
                continue
            db.add(
                ServiceRegionAvailability(
                    category_id=category.id,
                    region_id=region.id,
                    is_offered=True,
                    name_override=REGION_NAME_OVERRIDES.get((region_slug, cat_slug)),
                    sort_order=i,
                )
            )
            counts["availability"] += 1

    return counts


def seed_content(db: Session) -> dict[str, int]:
    counts = {
        "blocks": 0,
        "list_items": 0,
        "values": 0,
        "strengths": 0,
        "milestones": 0,
        "legal": 0,
        "contact": 0,
    }

    for row in CONTENT_BLOCKS:
        if _exists(db, ContentBlock, key=row["key"]):
            continue
        db.add(ContentBlock(**row))
        counts["blocks"] += 1

    for block_key, items in CONTENT_LIST_ITEMS.items():
        for i, text in enumerate(items, start=1):
            if _exists(db, ContentListItem, block_key=block_key, text=text):
                continue
            db.add(ContentListItem(block_key=block_key, text=text, sort_order=i))
            counts["list_items"] += 1

    for i, row in enumerate(CORE_VALUES, start=1):
        if not _exists(db, CoreValue, title=row["title"]):
            db.add(CoreValue(**row, sort_order=i))
            counts["values"] += 1

    for i, row in enumerate(KEY_STRENGTHS, start=1):
        if not _exists(db, KeyStrength, title=row["title"]):
            db.add(KeyStrength(**row, sort_order=i))
            counts["strengths"] += 1

    for i, row in enumerate(MILESTONES, start=1):
        if not _exists(db, Milestone, year_label=row["year_label"], title=row["title"]):
            db.add(Milestone(**row, sort_order=i))
            counts["milestones"] += 1

    for row in LEGAL_PAGES:
        if not _exists(db, LegalPage, slug=row["slug"]):
            db.add(LegalPage(**row))
            counts["legal"] += 1

    for row in CONTACT_DETAILS:
        if not _exists(db, ContactDetail, label=row["label"]):
            db.add(ContactDetail(**row))
            counts["contact"] += 1

    return counts


def seed_forms(db: Session) -> dict[str, int]:
    counts = {"forms": 0, "fields": 0}
    for spec in FORM_DEFINITIONS:
        form = db.execute(
            select(FormDefinition).where(FormDefinition.key == spec["key"])
        ).scalar_one_or_none()
        if form is None:
            form = FormDefinition(
                key=spec["key"],
                name=spec["name"],
                description=spec["description"],
            )
            db.add(form)
            db.flush()
            counts["forms"] += 1
        for i, field in enumerate(spec["fields"], start=1):
            if _exists(db, FormField, form_id=form.id, key=field["key"]):
                continue
            db.add(FormField(form_id=form.id, sort_order=i, **field))
            counts["fields"] += 1
    return counts


def seed_wizard(db: Session) -> dict[str, int]:
    counts = {"steps": 0, "questions": 0}
    for spec in WIZARD_STEPS:
        step = db.execute(
            select(WizardStep).where(WizardStep.key == spec["key"])
        ).scalar_one_or_none()
        if step is None:
            step = WizardStep(
                key=spec["key"],
                title=spec["title"],
                description=spec["description"],
                sort_order=spec["sort_order"],
            )
            db.add(step)
            db.flush()
            counts["steps"] += 1
        for i, question in enumerate(spec["questions"], start=1):
            if _exists(db, WizardQuestion, step_id=step.id, key=question["key"]):
                continue
            db.add(WizardQuestion(step_id=step.id, sort_order=i, **question))
            counts["questions"] += 1
    return counts


def seed_all(db: Session) -> dict[str, object]:
    result: dict[str, object] = {
        "settings": seed_settings(db),
        "services": seed_services(db),
        "content": seed_content(db),
        "forms": seed_forms(db),
        "wizard": seed_wizard(db),
    }
    db.commit()
    return result
