"""Model registry.

Importing every model here gives Alembic's autogenerate a complete view of the
metadata, and guarantees SQLAlchemy can resolve string-based relationships.
"""

from app.db.base import Base
from app.models.audit import AuditLog
from app.models.client import Client, client_services
from app.models.content import (
    Achievement,
    ContactDetail,
    ContentBlock,
    ContentListItem,
    CoreValue,
    KeyStrength,
    LegalPage,
    Milestone,
    Qualification,
    SocialLink,
    TeamMember,
    Testimonial,
)
from app.models.document import Document
from app.models.enquiry import Enquiry
from app.models.faq import FaqEmbedding, FaqEntry
from app.models.form_schema import FormDefinition, FormField
from app.models.invoice import Invoice
from app.models.note import Note
from app.models.onboarding import OnboardingResponse, WizardQuestion, WizardStep
from app.models.service import (
    Region,
    ServiceCategory,
    ServiceDetail,
    ServiceRegionAvailability,
    ServiceSubcategory,
    SubcategoryRegionAvailability,
)
from app.models.setting import Setting
from app.models.task import Task
from app.models.user import Invite, User, invite_services

__all__ = [
    "Base",
    "Achievement",
    "AuditLog",
    "Client",
    "client_services",
    "invite_services",
    "ContactDetail",
    "ContentBlock",
    "ContentListItem",
    "CoreValue",
    "Document",
    "Enquiry",
    "FaqEmbedding",
    "FaqEntry",
    "FormDefinition",
    "FormField",
    "Invite",
    "Invoice",
    "KeyStrength",
    "LegalPage",
    "Milestone",
    "Note",
    "OnboardingResponse",
    "Qualification",
    "Region",
    "ServiceCategory",
    "ServiceDetail",
    "ServiceRegionAvailability",
    "ServiceSubcategory",
    "Setting",
    "SocialLink",
    "SubcategoryRegionAvailability",
    "Task",
    "TeamMember",
    "Testimonial",
    "User",
    "WizardQuestion",
    "WizardStep",
]
