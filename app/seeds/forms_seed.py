"""Seed form definitions.

Both forms below are Section 13 open items (enquiry fields = item 1, profile
fields = item 3). They are seeded from the field lists the spec suggests, and
every one of them can be renamed, reordered, made optional, or removed from the
Admin Portal. Adding a field needs no migration and no deploy.
"""

from app.models.enums import FormFieldType as F

FORM_DEFINITIONS: list[dict] = [
    {
        "key": "enquiry",
        "name": "Website Enquiry Form",
        "description": (
            "Public enquiry / CTA form (spec 3.2). Field list is ASSUMED from the "
            "spec's suggestion and awaits SmartAWARE confirmation (Section 13 item 1)."
        ),
        "fields": [
            {"key": "name", "label": "Name", "field_type": F.TEXT, "is_required": True},
            {"key": "email", "label": "Email", "field_type": F.EMAIL, "is_required": True},
            {"key": "phone", "label": "Phone", "field_type": F.PHONE, "is_required": False},
            {"key": "country", "label": "Country", "field_type": F.COUNTRY, "is_required": False},
            {
                "key": "company_name",
                "label": "Company Name",
                "field_type": F.TEXT,
                "is_required": False,
            },
            {
                "key": "service_required",
                "label": "Services Required",
                # More than one, because an enquiry is rarely about exactly one
                # thing — a new company usually needs registration, bookkeeping
                # and payroll in the same breath.
                "field_type": F.MULTISELECT,
                "is_required": False,
                # Populated at render time from the live service taxonomy, so the
                # form and the website can never list different services.
                "options": [],
                "help_text": "Choose as many as apply.",
            },
            {
                "key": "sub_services",
                "label": "Specific Services",
                "field_type": F.MULTISELECT,
                "is_required": False,
                # Narrowed in the browser from the catalogue: which market, then
                # which services. Stored options would go stale the moment a
                # service was renamed for one market.
                "options": [],
                "help_text": "Follows from the country and services chosen above.",
            },
            {
                "key": "additional_information",
                "label": "Additional Information",
                "field_type": F.TEXTAREA,
                "is_required": False,
                "help_text": "Anything else you would like us to know. Optional.",
            },
        ],
    },
    {
        "key": "client_profile",
        "name": "Client Profile",
        "description": (
            "Customer Portal profile (spec 5.3.A). Fields backed by real columns on "
            "`clients`; any field added here beyond them is stored in `clients.extra`. "
            "Final list awaits SmartAWARE (Section 13 item 3)."
        ),
        "fields": [
            {
                "key": "company_name",
                "label": "Company Name",
                "field_type": F.TEXT,
                "is_required": True,
            },
            {
                "key": "owner_name",
                "label": "Owner / Director Name",
                "field_type": F.TEXT,
                "is_required": True,
            },
            {
                "key": "company_registration_number",
                "label": "Company Registration Number",
                "field_type": F.TEXT,
                "is_required": False,
            },
            {
                "key": "registration_date",
                "label": "Registration Date",
                "field_type": F.DATE,
                "is_required": False,
            },
            {
                "key": "address_line1",
                "label": "Business Address Line 1",
                "field_type": F.TEXT,
                "is_required": False,
            },
            {
                "key": "address_line2",
                "label": "Business Address Line 2",
                "field_type": F.TEXT,
                "is_required": False,
            },
            {"key": "city", "label": "Town / City", "field_type": F.TEXT, "is_required": False},
            {
                "key": "region_or_county",
                "label": "Region / County",
                "field_type": F.TEXT,
                "is_required": False,
            },
            {
                "key": "postcode",
                "label": "Postcode / PIN",
                "field_type": F.TEXT,
                "is_required": False,
            },
            {
                "key": "country",
                "label": "Country",
                "field_type": F.COUNTRY,
                "is_required": False,
            },
            {
                "key": "contact_email",
                "label": "Contact Email",
                "field_type": F.EMAIL,
                "is_required": False,
            },
            {
                "key": "contact_phone",
                "label": "Contact Phone",
                "field_type": F.PHONE,
                "is_required": False,
            },
        ],
    },
]
