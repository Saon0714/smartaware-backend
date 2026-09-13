"""Default runtime settings.

Every value here is a decision that spec Section 13 leaves open, or that the
spec requires to be admin-editable. They live as rows so SmartAWARE can change
any of them without a developer.

The `description` on each row is what the Admin Portal shows, so the reason for
a default is visible to the person changing it.
"""

from app.models.enums import SettingValueType as T

SETTINGS_DEFAULTS: list[dict] = [
    # --- Smart AI chatbot ---
    {
        "key": "chat_similarity_threshold",
        "value": 0.35,
        "value_type": T.FLOAT,
        "group": "chatbot",
        "description": (
            "Minimum cosine similarity for the chatbot to answer from the FAQ. "
            "Below this it shows the 'Please contact us' fallback. "
            "ASSUMED DEFAULT (Section 13 item 7), but measured rather than "
            "guessed: against the seeded FAQ with text-embedding-3-small, "
            "genuinely relevant questions scored 0.48-0.78 and irrelevant ones "
            "0.07-0.17, so 0.35 sits in the gap with margin on both sides. "
            "Raise it to answer only close matches; lower it to attempt more "
            "questions at the risk of weaker answers. Worth re-measuring once "
            "SmartAWARE's real FAQ set is in place."
        ),
    },
    {
        "key": "chat_top_k",
        "value": 5,
        "value_type": T.INTEGER,
        "group": "chatbot",
        "description": "Number of FAQ chunks retrieved per question.",
    },
    {
        "key": "chat_retention_days",
        "value": 30,
        "value_type": T.INTEGER,
        "group": "chatbot",
        "description": (
            "Days to retain chat transcripts before the nightly purge. "
            "Spec Section 4.5 default: 1 month."
        ),
    },
    {
        "key": "chat_logs_visible_to",
        "value": "admin",
        "value_type": T.STRING,
        "group": "chatbot",
        "description": (
            "Who may read chat transcripts: 'admin', 'admin_and_manager' or 'nobody'. "
            "ASSUMED DEFAULT (Section 13 item 8)."
        ),
    },
    # --- Accounts and access ---
    {
        "key": "invite_expiry_days",
        "value": 3,
        "value_type": T.INTEGER,
        "group": "accounts",
        "description": "Days before a sign-up invite expires. Spec Section 5.1 default: 3.",
    },
    {
        "key": "allow_multiple_admins",
        "value": False,
        "value_type": T.BOOLEAN,
        "group": "accounts",
        "description": (
            "Whether more than one Admin account may exist. "
            "ASSUMED DEFAULT (Section 13 item 4): single primary Admin."
        ),
    },
    {
        "key": "manager_client_scope",
        "value": "assigned",
        "value_type": T.STRING,
        "group": "accounts",
        "description": (
            "Which clients a Manager can see: 'assigned' or 'all'. "
            "ASSUMED DEFAULT (Section 13 item 5): assigned only, least privilege."
        ),
    },
    {
        "key": "manager_can_manage_content",
        "value": False,
        "value_type": T.BOOLEAN,
        "group": "accounts",
        "description": (
            "Whether Managers may edit FAQ and website content. "
            "ASSUMED DEFAULT (Section 13 item 6): Admin only."
        ),
    },
    {
        "key": "mfa_required_roles",
        "value": [],
        "value_type": T.JSON,
        "group": "security",
        "description": (
            "Roles that must complete MFA at login, e.g. ['admin','manager']. "
            "ASSUMED DEFAULT (Section 13 item 11): none — columns exist, "
            "enforcement is off until SmartAWARE confirms."
        ),
    },
    # --- Documents ---
    {
        "key": "document_versioning",
        "value": "keep",
        "value_type": T.STRING,
        "group": "documents",
        "description": (
            "'keep' retains superseded versions; 'overwrite' replaces them. "
            "ASSUMED DEFAULT (Section 13 item 12): keep — safer for tax records."
        ),
    },
    # --- Notifications (Section 7: recipients must be configurable) ---
    {
        "key": "notify_enquiry_recipients",
        "value": [],
        "value_type": T.JSON,
        "group": "notifications",
        "description": (
            "Email addresses notified of website enquiries. "
            "EMPTY — awaiting SmartAWARE. No enquiry email is sent until set."
        ),
    },
    {
        "key": "notify_document_recipients",
        "value": [],
        "value_type": T.JSON,
        "group": "notifications",
        "description": (
            "Email addresses notified when a client uploads a document. "
            "EMPTY — awaiting SmartAWARE."
        ),
    },
    # --- Content editorial guidance ---
    {
        "key": "service_short_description_min_words",
        "value": 32,
        "value_type": T.INTEGER,
        "group": "content",
        "description": (
            "Soft lower bound for service short descriptions (spec 3.1: 32-40 words). "
            "Shown as a hint in the admin editor; never rejected — the supplied "
            "copy is shorter than this and is still valid."
        ),
    },
    {
        "key": "service_short_description_max_words",
        "value": 40,
        "value_type": T.INTEGER,
        "group": "content",
        "description": "Soft upper bound for service short descriptions.",
    },
    # --- Payments (Section 12) ---
    {
        "key": "wise_payment_link_base_url",
        "value": "",
        "value_type": T.STRING,
        "group": "payments",
        "description": (
            "The Open Payment Link copied from the Wise Business dashboard. "
            "Amount, currency and invoice reference are appended as query "
            "parameters. EMPTY — awaiting SmartAWARE's real link; 'Pay Now' "
            "stays disabled until it is set. No Wise API call is ever made "
            "(spec 12.1)."
        ),
    },
]
