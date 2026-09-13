"""Region and service taxonomy schemas.

The same taxonomy serves the public website and the internal task tracker, so
these shapes are shared rather than duplicated per consumer.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Regions ------------------------------------------------------------------


class RegionOut(_Out):
    id: uuid.UUID
    slug: str
    name: str
    display_name: str
    currency_code: str | None
    sort_order: int
    is_published: bool
    meta_title: str | None
    meta_description: str | None


class RegionWrite(BaseModel):
    slug: str = Field(max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(max_length=128)
    display_name: str = Field(max_length=255)
    currency_code: str | None = Field(default=None, max_length=3)
    sort_order: int = 0
    is_published: bool = True
    meta_title: str | None = Field(default=None, max_length=255)
    meta_description: str | None = Field(default=None, max_length=500)


# --- Subcategories and bullets -------------------------------------------------


class ServiceSubcategoryOut(_Out):
    id: uuid.UUID
    category_id: uuid.UUID
    slug: str
    name: str
    description: str | None
    sort_order: int
    is_published: bool
    is_archived: bool


class ServiceSubcategoryWrite(BaseModel):
    name: str = Field(max_length=255)
    slug: str | None = Field(
        default=None,
        max_length=160,
        description="Derived from the name when omitted.",
    )
    description: str | None = None
    sort_order: int = 0
    #: Subcategories drive task categorisation; publishing one to the website is
    #: a deliberate choice, so the default is off.
    is_published: bool = False


class ServiceDetailOut(_Out):
    id: uuid.UUID
    category_id: uuid.UUID
    text: str
    sort_order: int


class ServiceDetailWrite(BaseModel):
    text: str
    sort_order: int = 0


# --- Categories ---------------------------------------------------------------


class ServiceCategorySummary(_Out):
    id: uuid.UUID
    slug: str
    name: str
    short_description: str | None
    icon_key: str | None
    sort_order: int


class ServiceCategoryOut(ServiceCategorySummary):
    long_description: str | None
    cta_label: str | None
    cta_url: str | None
    is_published: bool
    is_archived: bool
    meta_title: str | None
    meta_description: str | None
    details: list[ServiceDetailOut] = Field(default_factory=list)
    subcategories: list[ServiceSubcategoryOut] = Field(default_factory=list)


class ServiceCategoryWrite(BaseModel):
    name: str = Field(max_length=255)
    slug: str | None = Field(
        default=None,
        max_length=128,
        description="Derived from the name when omitted.",
    )
    short_description: str | None = None
    long_description: str | None = None
    icon_key: str | None = Field(default=None, max_length=64)
    cta_label: str | None = Field(default=None, max_length=128)
    cta_url: str | None = Field(default=None, max_length=512)
    sort_order: int = 0
    is_published: bool = True
    meta_title: str | None = Field(default=None, max_length=255)
    meta_description: str | None = Field(default=None, max_length=500)


# --- Region availability -------------------------------------------------------


class AvailabilityOut(_Out):
    id: uuid.UUID
    category_id: uuid.UUID
    region_id: uuid.UUID
    is_offered: bool
    name_override: str | None
    short_description_override: str | None
    long_description_override: str | None
    sort_order: int


class AvailabilityWrite(BaseModel):
    """Upserted per (category, region) pair."""

    is_offered: bool = True
    name_override: str | None = Field(default=None, max_length=255)
    short_description_override: str | None = None
    long_description_override: str | None = None
    sort_order: int = 0


class CategoryAvailabilityRow(BaseModel):
    """One cell of the admin availability grid."""

    region_id: uuid.UUID
    region_slug: str
    region_name: str
    is_offered: bool
    name_override: str | None
    short_description_override: str | None
    sort_order: int


class CategoryAvailabilityGrid(BaseModel):
    category_id: uuid.UUID
    category_slug: str
    category_name: str
    regions: list[CategoryAvailabilityRow]


# --- Public, region-resolved shapes -------------------------------------------


class RegionalServiceSummary(BaseModel):
    """A service as offered in one market, with overrides already applied.

    The frontend never has to know an override existed — it receives the name
    and wording that market should show.
    """

    id: uuid.UUID
    slug: str
    name: str
    short_description: str | None
    icon_key: str | None
    sort_order: int


class RegionalServiceDetail(RegionalServiceSummary):
    long_description: str | None
    cta_label: str | None
    cta_url: str | None
    meta_title: str | None
    meta_description: str | None
    details: list[str] = Field(default_factory=list)
    subcategories: list[str] = Field(
        default_factory=list,
        description="Published subcategories offered in this market.",
    )
    other_regions: list[RegionOut] = Field(
        default_factory=list,
        description="Other markets offering this service.",
    )


class RegionServicesOut(BaseModel):
    region: RegionOut
    services: list[RegionalServiceSummary]


class ServiceHubCategory(ServiceCategorySummary):
    """A category on the /services hub, with the markets offering it."""

    region_slugs: list[str] = Field(default_factory=list)


class ServiceHubOut(BaseModel):
    regions: list[RegionOut]
    categories: list[ServiceHubCategory]
