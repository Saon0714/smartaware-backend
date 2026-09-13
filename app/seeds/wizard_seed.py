"""Seed the onboarding / Tax Wizard.

Spec Section 13 item 2: the real question set is unconfirmed. This is a minimal
PLACEHOLDER sequence that exercises the engine end to end. SmartAWARE replaces
it entirely from the Admin Portal — steps and questions are rows, so the real
wizard needs no code.
"""

from app.models.enums import FormFieldType as F

WIZARD_STEPS: list[dict] = [
    {
        "key": "business_basics",
        "title": "About your business",
        "description": "PLACEHOLDER STEP — replace with SmartAWARE's confirmed questions.",
        "sort_order": 1,
        "questions": [
            {
                "key": "entity_type",
                "label": "What type of entity are you?",
                "field_type": F.SELECT,
                "is_required": True,
                "options": [
                    "Individual",
                    "Sole Trader",
                    "Partnership",
                    "Limited Company",
                    "LLP",
                    "Other",
                ],
            },
            {
                "key": "primary_region",
                "label": "Which market are your tax obligations primarily in?",
                "field_type": F.SELECT,
                "is_required": True,
                "options": ["United Kingdom", "India", "United Arab Emirates", "Oman"],
            },
        ],
    },
    {
        "key": "services_needed",
        "title": "What do you need help with?",
        "description": "PLACEHOLDER STEP — replace with SmartAWARE's confirmed questions.",
        "sort_order": 2,
        "questions": [
            {
                "key": "services_of_interest",
                "label": "Which services are you interested in?",
                "field_type": F.MULTISELECT,
                "is_required": False,
                "options": [],
                "help_text": "Options are sourced from the published service categories.",
            },
            {
                "key": "current_accountant",
                "label": "Do you currently have an accountant?",
                "field_type": F.RADIO,
                "is_required": False,
                "options": ["Yes", "No"],
            },
        ],
    },
    {
        "key": "contact_preferences",
        "title": "How should we reach you?",
        "description": "PLACEHOLDER STEP — replace with SmartAWARE's confirmed questions.",
        "sort_order": 3,
        "questions": [
            {
                "key": "preferred_contact",
                "label": "Preferred contact method",
                "field_type": F.SELECT,
                "is_required": False,
                "options": ["Email", "Phone", "WhatsApp"],
            },
            {
                "key": "notes",
                "label": "Anything else we should know?",
                "field_type": F.TEXTAREA,
                "is_required": False,
            },
        ],
    },
]
