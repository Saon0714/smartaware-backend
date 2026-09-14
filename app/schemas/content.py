"""Website content schemas.

Every public page is assembled from these, so nothing on the marketing site is
hardcoded in either repository. Spec Section 3.1 and Section 4.3 treat that as
an architectural constraint rather than a convenience.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Content blocks -----------------------------------------------------------


class ContentBlockOut(_Out):
    id: uuid.UUID
    key: str
    title: str | None
    subtitle: str | None
    body: str | None
    sort_order: int
    is_published: bool
    items: list[str] = Field(default_factory=list, description="Ordered bullet list.")


class ContentBlockUpdate(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    body: str | None = None
    sort_order: int | None = None
    is_published: bool | None = None


class ContentListItemOut(_Out):
    id: uuid.UUID
    block_key: str
    text: str
    sort_order: int
    is_published: bool


class ContentListItemCreate(BaseModel):
    block_key: str = Field(max_length=128)
    text: str
    sort_order: int = 0
    is_published: bool = True


class ContentListItemUpdate(BaseModel):
    text: str | None = None
    sort_order: int | None = None
    is_published: bool | None = None


# --- Simple ordered lists -----------------------------------------------------


class CoreValueOut(_Out):
    id: uuid.UUID
    title: str
    description: str
    icon_key: str | None
    sort_order: int
    is_published: bool


class CoreValueWrite(BaseModel):
    title: str = Field(max_length=255)
    description: str
    icon_key: str | None = Field(default=None, max_length=64)
    sort_order: int = 0
    is_published: bool = True


class KeyStrengthOut(CoreValueOut):
    pass


class KeyStrengthWrite(CoreValueWrite):
    pass


class MilestoneOut(_Out):
    id: uuid.UUID
    year_label: str
    title: str
    body: str | None
    sort_order: int
    is_published: bool


class MilestoneWrite(BaseModel):
    year_label: str = Field(max_length=64)
    title: str = Field(max_length=255)
    body: str | None = None
    sort_order: int = 0
    is_published: bool = True


class TeamMemberOut(_Out):
    id: uuid.UUID
    name: str
    designation: str | None
    qualifications: str | None
    areas_of_expertise: str | None
    professional_experience: str | None
    photo_s3_key: str | None
    sort_order: int
    is_published: bool


class TeamMemberWrite(BaseModel):
    name: str = Field(max_length=255)
    designation: str | None = Field(default=None, max_length=255)
    qualifications: str | None = None
    areas_of_expertise: str | None = None
    professional_experience: str | None = None
    photo_s3_key: str | None = Field(default=None, max_length=1024)
    sort_order: int = 0
    #: Unpublished by default. The content brief permits only verified people
    #: and credentials to appear publicly, so publishing is a deliberate act.
    is_published: bool = False


class QualificationOut(_Out):
    id: uuid.UUID
    name: str
    issuer: str | None
    qualification_type: str | None
    reference: str | None
    is_verified: bool
    sort_order: int
    is_published: bool


class QualificationWrite(BaseModel):
    name: str = Field(max_length=255)
    issuer: str | None = Field(default=None, max_length=255)
    qualification_type: str | None = Field(default=None, max_length=128)
    reference: str | None = Field(default=None, max_length=255)
    is_verified: bool = False
    sort_order: int = 0
    is_published: bool = False


class AchievementOut(_Out):
    id: uuid.UUID
    label: str
    value: str
    unit: str | None
    sort_order: int
    is_published: bool


class AchievementWrite(BaseModel):
    label: str = Field(max_length=255)
    value: str = Field(max_length=64)
    unit: str | None = Field(default=None, max_length=64)
    sort_order: int = 0
    is_published: bool = False


class TestimonialOut(_Out):
    id: uuid.UUID
    author_name: str
    author_company: str | None
    author_region: str | None
    quote: str
    rating: int | None
    sort_order: int
    is_published: bool
    #: "placeholder", "manual", or the service it came from. Public because
    #: Trustpilot's terms require a review shown on a site to be attributed and
    #: linked back, and because the site should be able to say when a quote is
    #: still sample copy.
    source: str = "manual"
    source_url: str | None = None
    reviewed_at: date | None = None


class TestimonialWrite(BaseModel):
    author_name: str = Field(max_length=255)
    author_company: str | None = Field(default=None, max_length=255)
    author_region: str | None = Field(default=None, max_length=128)
    quote: str
    rating: int | None = Field(default=None, ge=1, le=5)
    sort_order: int = 0
    is_published: bool = False
    #: `source` and `external_id` are deliberately absent: they identify where a
    #: review came from, and a quote typed into the Admin Portal came from
    #: SmartAWARE. Letting an editor claim a review was imported would make the
    #: attribution the site displays untrue.
    source_url: str | None = Field(default=None, max_length=512)
    reviewed_at: date | None = None


class ContactDetailOut(_Out):
    id: uuid.UUID
    label: str
    detail_type: str
    value: str
    region_id: uuid.UUID | None
    sort_order: int
    is_published: bool


class ContactDetailWrite(BaseModel):
    label: str = Field(max_length=255)
    detail_type: str = Field(
        max_length=64,
        description="address | phone | whatsapp | email | hours | map | department",
    )
    value: str
    region_id: uuid.UUID | None = None
    sort_order: int = 0
    is_published: bool = True


class SocialLinkOut(_Out):
    id: uuid.UUID
    platform: str
    url: str
    sort_order: int
    is_published: bool


class SocialLinkWrite(BaseModel):
    platform: str = Field(max_length=64)
    url: str = Field(max_length=512)
    sort_order: int = 0
    is_published: bool = True


# --- Legal pages --------------------------------------------------------------


class LegalPageSummary(_Out):
    slug: str
    title: str


class LegalPageOut(_Out):
    id: uuid.UUID
    slug: str
    title: str
    body: str
    version: str | None
    effective_from: date | None
    is_published: bool
    updated_at: datetime


class LegalPageUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    body: str | None = None
    version: str | None = Field(default=None, max_length=32)
    effective_from: date | None = None
    is_published: bool | None = None


# --- Aggregated public payloads -----------------------------------------------


class ServiceTeaser(_Out):
    """Minimal service shape for the homepage. The full service pages, region
    availability and admin management arrive in Chunk 4."""

    id: uuid.UUID
    slug: str
    name: str
    short_description: str | None
    icon_key: str | None


class HomePageOut(BaseModel):
    hero: ContentBlockOut | None
    core_values: list[CoreValueOut] = Field(default_factory=list)
    key_strengths: list[KeyStrengthOut]
    services: list[ServiceTeaser]
    achievements: list[AchievementOut]
    testimonials: list[TestimonialOut]


class AboutPageOut(BaseModel):
    """Mirrors the section order the Website Content Brief specifies."""

    intro: ContentBlockOut | None
    presence: ContentBlockOut | None
    vision: ContentBlockOut | None
    mission: ContentBlockOut | None
    data_protection: ContentBlockOut | None
    why_choose_us: ContentBlockOut | None
    why_choose_us_closing: ContentBlockOut | None
    core_values: list[CoreValueOut]
    key_strengths: list[KeyStrengthOut]
    milestones: list[MilestoneOut]
    team: list[TeamMemberOut]
    qualifications: list[QualificationOut]
    achievements: list[AchievementOut]
    testimonials: list[TestimonialOut]


class ContactPageOut(BaseModel):
    details: list[ContactDetailOut]
    social_links: list[SocialLinkOut]


class ReorderRequest(BaseModel):
    """Ordered ids. Position in the list becomes sort_order."""

    ids: list[uuid.UUID] = Field(min_length=1)
