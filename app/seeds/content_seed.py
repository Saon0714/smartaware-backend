"""Website copy, seeded from SmartAWARE's Website Content Brief.

Prose the brief actually wrote is seeded verbatim — it is approved copy.

Four tables are deliberately seeded EMPTY: team members, professional
qualifications, business achievements and testimonials. The brief is explicit
that only verified credentials and verified achievements may be published, and
these are factual claims about a real firm and real people. Inventing a client
count or a plausible-looking certification would put fabricated claims on a
public website. Admin populates them.

Legal pages are seeded as clearly-marked placeholders for the same reason: a
privacy policy is a legal instrument that must describe SmartAWARE's actual
practices.
"""

CONTENT_BLOCKS: list[dict] = [
    {
        "key": "home_hero",
        # {region} is replaced with the visitor's chosen market. Editable like
        # any other copy — an editor can move it, reword around it, or drop it
        # entirely, in which case the heading is simply the same everywhere.
        "title": "Professional {region} Tax & Compliance Advisory",
        "subtitle": (
            "Supporting individuals and businesses across the United Kingdom, "
            "India, the UAE and Oman."
        ),
        "body": (
            "SmartAWARE is a professional tax, accounting and compliance advisory "
            "firm serving individuals, businesses and organisations with their "
            "financial and statutory requirements."
        ),
        "sort_order": 1,
    },
    {
        "key": "about_intro",
        "title": "About SmartAWARE",
        "subtitle": "Professional UK Tax & Compliance Advisory",
        "body": (
            "SmartAWARE is a professional tax, accounting and compliance advisory firm "
            "serving individuals, businesses and organisations with their financial and "
            "statutory requirements.\n\n"
            "Established in 2016, SmartAWARE has developed its principal professional "
            "presence in the United Kingdom, supporting clients with practical and "
            "reliable tax and compliance services.\n\n"
            "From 2020, we began expanding our international reach, building client "
            "relationships and supporting businesses and individuals across India, the "
            "United Arab Emirates and Oman in the GCC region.\n\n"
            "Our approach combines professional expertise, attention to detail and a "
            "commitment to providing dependable, client-focused solutions.\n\n"
            "We aim to make tax, accounting and compliance easier to understand and "
            "manage, allowing our clients to focus on their personal, professional and "
            "business priorities."
        ),
        "sort_order": 2,
    },
    {
        "key": "our_presence_today",
        "title": "Our Presence Today",
        "body": (
            "Today, SmartAWARE's major work is focused on the United Kingdom, with an "
            "international presence supporting clients in India, the United Arab "
            "Emirates and Oman.\n\n"
            "Our international experience enables us to assist clients with their UK tax "
            "and compliance requirements while also supporting relevant accounting, tax "
            "and business needs in the markets we serve."
        ),
        "sort_order": 3,
    },
    {
        "key": "vision",
        "title": "Our Vision",
        "body": (
            "To become a trusted global name in tax, accounting and compliance advisory "
            "services, recognised for professional excellence, client confidence and "
            "long-term relationships.\n\n"
            "We aspire to make professional tax and compliance support accessible to "
            "individuals and businesses across the United Kingdom, India and the GCC region."
        ),
        "sort_order": 4,
    },
    {
        "key": "mission",
        "title": "Our Mission",
        "body": (
            "Our mission is to simplify tax, accounting and compliance for our clients by "
            "providing accurate, timely and practical professional support.\n\n"
            "We aim to:"
        ),
        "sort_order": 5,
    },
    {
        "key": "data_protection",
        "title": "Our Commitment to Client Data Protection",
        "body": (
            "At SmartAWARE, we understand the importance of protecting sensitive "
            "financial and personal information.\n\n"
            "We follow applicable GDPR requirements and maintain appropriate data "
            "protection practices to support the confidentiality, integrity and security "
            "of client information.\n\n"
            "Our website and client-facing systems are designed with data protection in "
            "mind, using AWS-hosted infrastructure and private encrypted server "
            "environments, together with appropriate security controls.\n\n"
            "We are committed to handling client information responsibly and maintaining "
            "trust through secure and professional service delivery."
        ),
        "sort_order": 6,
    },
    {
        "key": "why_choose_us",
        "title": "Why Choose SmartAWARE?",
        "body": (
            "Choosing the right tax and compliance advisor is an important decision.\n\n"
            "At SmartAWARE, we believe clients deserve professional support that is "
            "clear, dependable and tailored to their requirements.\n\n"
            "Our experience since 2016, strong focus on the United Kingdom and "
            "international expansion from 2020 reflect our commitment to supporting "
            "clients across the markets we serve.\n\n"
            "We aim to provide:"
        ),
        "sort_order": 7,
    },
    {
        "key": "why_choose_us_closing",
        "body": (
            "Our goal is to make tax, accounting and compliance easier to manage, "
            "allowing our clients to focus on their personal, professional and business "
            "priorities."
        ),
        "sort_order": 8,
    },
    {
        # The footer's standfirst. It was the last piece of public prose still
        # written into the frontend, which put it out of reach of the people
        # who own the wording.
        "key": "footer_blurb",
        "title": "Footer introduction",
        "body": (
            "Professional tax, accounting and compliance advisory services for "
            "individuals and businesses in the United Kingdom, India, the UAE "
            "and Oman."
        ),
        "sort_order": 9,
    },
]

CONTENT_LIST_ITEMS: dict[str, list[str]] = {
    "mission": [
        "Deliver reliable UK tax and compliance services.",
        "Support clients with relevant accounting and tax requirements in India, the UAE and Oman.",
        "Help individuals and businesses understand and meet their statutory obligations.",
        "Provide personalised solutions based on individual and business circumstances.",
        "Support clients with international tax and compliance requirements.",
        "Maintain transparency, professionalism and confidentiality.",
        "Build lasting relationships through consistent service quality.",
    ],
    "why_choose_us": [
        "Professional and approachable service.",
        "Clear communication and practical guidance.",
        "Reliable support with tax and compliance matters.",
        "A commitment to accuracy and confidentiality.",
        "Experience supporting international clients.",
        "Appropriate data protection and information security practices.",
        "Long-term professional relationships.",
    ],
}

CORE_VALUES: list[dict] = [
    {
        "title": "Integrity",
        "description": "We believe in honest, transparent and ethical professional relationships.",
        "icon_key": "scale",
    },
    {
        "title": "Professionalism",
        "description": "We maintain high standards of accuracy, responsibility and client service.",
        "icon_key": "briefcase",
    },
    {
        "title": "Client Focus",
        "description": (
            "We take time to understand our clients' requirements and provide practical "
            "solutions suited to their circumstances."
        ),
        "icon_key": "target",
    },
    {
        "title": "Reliability",
        "description": (
            "We value timely communication, dependable service and meeting agreed commitments."
        ),
        "icon_key": "clock",
    },
    {
        "title": "Confidentiality and Data Protection",
        "description": (
            "We understand the importance of protecting sensitive financial and personal "
            "information. SmartAWARE follows applicable GDPR requirements and maintains "
            "appropriate data protection practices to safeguard client information."
        ),
        "icon_key": "lock",
    },
    {
        "title": "Continuous Improvement",
        "description": (
            "We continually seek to improve our knowledge, processes and service delivery "
            "to meet the changing needs of our clients."
        ),
        "icon_key": "trending-up",
    },
]

#: Icons are part of the seed rather than left blank. Without one the website
#: falls back to the item's position — "01", "02" — which says nothing about the
#: strength it sits beside. Editors can change them in the Admin Portal.
KEY_STRENGTHS: list[dict] = [
    {
        "title": "Experience Since 2016",
        "description": (
            "SmartAWARE has developed experience in supporting individuals and businesses "
            "with tax, accounting and compliance requirements since 2016."
        ),
        "icon_key": "award",
    },
    {
        "title": "Strong UK Focus",
        "description": (
            "The United Kingdom is our primary market, with services focused on helping "
            "individuals and businesses manage their UK tax and compliance responsibilities."
        ),
        "icon_key": "map-pin",
    },
    {
        "title": "International Reach",
        "description": (
            "Since 2020, we have expanded our global reach, supporting clients in India, "
            "the UAE and Oman."
        ),
        "icon_key": "globe",
    },
    {
        "title": "Comprehensive Accounting & Tax Services",
        "description": (
            "Our service categories cover personal tax, company accounting, bookkeeping, "
            "VAT, payroll, CIS, business registration, tax advisory and compliance."
        ),
        "icon_key": "layers",
    },
    {
        "title": "Personalised Professional Service",
        "description": (
            "We understand that every client has different financial, personal and "
            "business circumstances. Our services are tailored to individual requirements."
        ),
        "icon_key": "user-check",
    },
    {
        "title": "Secure Data Protection",
        "description": (
            "Protecting client information is a key priority at SmartAWARE. We follow "
            "applicable GDPR requirements and use AWS-hosted infrastructure alongside "
            "private, highly encrypted server environments and appropriate security "
            "controls to support the protection of sensitive client data."
        ),
        "icon_key": "shield",
    },
    {
        "title": "Professional Communication",
        "description": (
            "We believe clear communication and timely updates are essential to building "
            "client confidence."
        ),
        "icon_key": "message",
    },
]

#: Placeholder reviews, so the carousel can be seen working before Trustpilot
#: is connected. They are NOT real client feedback.
#:
#: What keeps that honest is `source="placeholder"`, not the wording: the
#: Trustpilot import deletes everything from that source on its first
#: successful run, so nobody has to remember to clear them out, and the Admin
#: Portal lists the source against every row. Real reviews arrive as
#: source="trustpilot" with an `external_id`; anything typed in the Admin
#: Portal is source="manual" and is never touched by an import.
#:
#: Attributed to a role at an invented company rather than to a named person.
#: The companies are obvious composites, and putting words in the mouth of a
#: person who does not exist is a line worth not crossing even in sample copy.
PLACEHOLDER_TESTIMONIALS: list[dict] = [
    {
        "author_name": "Managing Director",
        "author_company": "Northgate Logistics Ltd",
        "author_region": "United Kingdom",
        "quote": (
            "Clear advice and a straightforward process from start to finish. "
            "Our year-end accounts were filed well ahead of the deadline and "
            "every question was answered the same day."
        ),
        "rating": 5,
    },
    {
        "author_name": "Finance Manager",
        "author_company": "Sunvale Textiles",
        "author_region": "India",
        "quote": (
            "They took the time to understand how our business actually works "
            "before recommending anything. The monthly bookkeeping has been "
            "accurate and on time all year."
        ),
        "rating": 5,
    },
    {
        "author_name": "Operations Director",
        "author_company": "Crescent Bay Trading",
        "author_region": "United Arab Emirates",
        "quote": (
            "VAT registration and the first returns were handled without any "
            "fuss. Having one point of contact who knows the account makes a "
            "real difference."
        ),
        "rating": 4,
    },
    {
        "author_name": "Managing Partner",
        "author_company": "Ridgeway Contracting",
        "author_region": "Oman",
        "quote": (
            "Responsive, professional and easy to deal with. We always know "
            "what is outstanding and what is coming up next."
        ),
        "rating": 5,
    },
]

MILESTONES: list[dict] = [
    {
        "year_label": "2016",
        "title": "SmartAWARE Begins Its Journey",
        "body": (
            "SmartAWARE was established with the objective of providing professional tax "
            "and compliance support to individuals and businesses. From the outset, our "
            "focus has been on delivering practical guidance, maintaining professional "
            "standards and building long-term relationships with our clients."
        ),
    },
    {
        "year_label": "2020",
        "title": "Global Expansion",
        "body": (
            "SmartAWARE began expanding its services globally, with a primary focus on "
            "the United Kingdom and growing client relationships in India and the GCC "
            "region. This expansion enabled us to support clients across different "
            "jurisdictions and understand the varied tax, accounting and compliance "
            "requirements of individuals and businesses operating internationally."
        ),
    },
    {
        "year_label": "2020 Onwards",
        "title": "International Client Support",
        "body": (
            "We continued to develop our professional services and support clients across "
            "the UK, India, the UAE and Oman."
        ),
    },
]

# Placeholders only. Legal text must come from SmartAWARE or their advisers.
LEGAL_PAGES: list[dict] = [
    {
        "slug": "privacy-policy",
        "title": "Privacy Policy",
        "body": (
            "[PLACEHOLDER — NOT PUBLISHED]\n\n"
            "This page requires SmartAWARE's actual privacy policy. It must describe the "
            "personal data genuinely collected, the lawful basis for processing, "
            "retention periods, third-party processors (AWS, OpenAI, Wise) and how data "
            "subjects exercise their GDPR rights.\n\n"
            "It has deliberately not been drafted here: a privacy policy is a legal "
            "statement about real practices and cannot be generated from a template."
        ),
        "is_published": False,
    },
    {
        "slug": "cookie-policy",
        "title": "Cookie Policy",
        "body": (
            "[PLACEHOLDER — NOT PUBLISHED]\n\n"
            "Requires SmartAWARE's confirmation of which cookies the live site sets, "
            "including any analytics, and the consent mechanism used."
        ),
        "is_published": False,
    },
    {
        "slug": "terms-of-service",
        "title": "Terms of Service",
        "body": (
            "[PLACEHOLDER — NOT PUBLISHED]\n\n"
            "Requires SmartAWARE's engagement terms and portal terms of use."
        ),
        "is_published": False,
    },
]

# The brief specifies a Contact page but supplies no actual details, so these
# are labelled placeholders rather than invented addresses or phone numbers.
#: Supplied by SmartAWARE.
#:
#: Numbers are stored in international format even where a national one was
#: given, because `tel:` and `wa.me` links only work from abroad that way — and
#: this site is read in four countries.
#:
#: The new-business numbers are scoped to a market, which is what `region_id`
#: on this table is for: a visitor who has chosen Oman should be given the Oman
#: number first. They are labelled by market rather than by the person who
#: answers them — a name on a public page is that person's to volunteer.
CONTACT_DETAILS: list[dict] = [
    {
        "label": "Registered Office",
        "detail_type": "address",
        "value": (
            "Office 19228\n"
            "182-184 High St North\n"
            "East Ham\n"
            "London\n"
            "E6 2JA"
        ),
        "is_published": True,
        "sort_order": 1,
    },
    {
        "label": "General Enquiries",
        "detail_type": "email",
        "value": "info@smartaware.co.uk",
        "is_published": True,
        "sort_order": 2,
    },
    {
        "label": "Telephone",
        "detail_type": "phone",
        "value": "+44 20 3051 6990",
        "is_published": True,
        "sort_order": 3,
    },
    {
        "label": "WhatsApp",
        "detail_type": "whatsapp",
        "value": "+44 20 3051 6990",
        "is_published": True,
        "sort_order": 4,
    },
    {
        "label": "Working Hours",
        "detail_type": "hours",
        "value": (
            "8am to 5pm BST, Monday to Friday\n"
            "Closed weekends and UK bank holidays"
        ),
        "is_published": True,
        "sort_order": 5,
    },
    {
        "label": "Find Us",
        "detail_type": "map",
        "value": "https://maps.app.goo.gl/eMpxVM8orNPKhW6w5",
        "is_published": True,
        "sort_order": 6,
    },
    {
        "label": "New Business Enquiries — United Kingdom",
        "detail_type": "department",
        "value": "+44 7588 755131",
        "region_slug": "uk",
        "is_published": True,
        "sort_order": 10,
    },
    {
        "label": "New Business Enquiries — India",
        "detail_type": "department",
        "value": "+91 94743 00860",
        "region_slug": "india",
        "is_published": True,
        "sort_order": 11,
    },
    {
        "label": "New Business Enquiries — United Arab Emirates",
        "detail_type": "department",
        "value": "+971 58 603 2026",
        "region_slug": "uae",
        "is_published": True,
        "sort_order": 12,
    },
    {
        "label": "New Business Enquiries — Oman",
        "detail_type": "department",
        "value": "+968 7786 9366",
        "region_slug": "oman",
        "is_published": True,
        "sort_order": 13,
    },
]

SOCIAL_LINKS: list[dict] = [
    {
        "platform": "LinkedIn",
        "url": "https://uk.linkedin.com/company/smartawareuk",
        "is_published": True,
        "sort_order": 1,
    },
    {
        "platform": "Facebook",
        "url": "https://www.facebook.com/SmartAWARE.UK",
        "is_published": True,
        "sort_order": 2,
    },
]
