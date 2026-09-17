"""Editing constraints for each runtime setting.

The `settings` table stores a key, a JSON value and a type. That is enough to
read a value but not enough to edit one safely: nothing there says the
escalation threshold is a fraction, that manager scope is one of two words, or
that the notification lists hold email addresses.

Those rules live here rather than in the table because they are properties of
the code that consumes each setting — changing them means changing that code
too. The API validates against this, and the Admin Portal uses the same
description to render an appropriate control instead of a bare text box.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.core.settings_service import SettingKey

Control = Literal["number", "toggle", "text", "choice", "multi_choice", "email_list"]


@dataclass(frozen=True)
class SettingSpec:
    control: Control
    label: str
    #: For `choice` and `multi_choice`: allowed values paired with what to show
    #: the editor. A `multi_choice` value is the list of values chosen.
    choices: tuple[tuple[str, str], ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    #: Guidance shown beneath the control, beyond the stored description.
    hint: str | None = None
    unit: str | None = None
    #: Settings whose effect is worth confirming before saving.
    confirm: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)


SETTING_SPECS: dict[str, SettingSpec] = {
    SettingKey.CHAT_SIMILARITY_THRESHOLD: SettingSpec(
        control="number",
        label="Escalation threshold",
        minimum=0.0,
        maximum=1.0,
        hint=(
            "How close a question must be to an FAQ entry before Smart AI will "
            "answer it. Lower attempts more questions; higher answers only close "
            "matches. Measured against the current FAQ, relevant questions score "
            "roughly 0.48–0.78 and irrelevant ones 0.07–0.17."
        ),
    ),
    SettingKey.CHAT_TOP_K: SettingSpec(
        control="number",
        label="FAQ entries retrieved per question",
        minimum=1,
        maximum=20,
    ),
    SettingKey.INVITE_EXPIRY_DAYS: SettingSpec(
        control="number",
        label="Invitation link expiry",
        minimum=1,
        maximum=90,
        unit="days",
        hint="Applies to invitations sent from now on, not ones already issued.",
    ),
    SettingKey.ALLOW_MULTIPLE_ADMINS: SettingSpec(
        control="toggle",
        label="Allow more than one administrator",
        confirm=(
            "Administrators can change account status, delete tasks and manage "
            "every setting including this one. Only enable this if a second "
            "person genuinely needs that authority."
        ),
    ),
    SettingKey.MANAGER_CLIENT_SCOPE: SettingSpec(
        control="choice",
        label="Which clients a manager can see",
        choices=(
            ("assigned", "Only clients assigned to them"),
            ("all", "Every client"),
        ),
        confirm=(
            "Setting this to every client gives all managers access to all "
            "client records, including those they are not working on."
        ),
    ),
    SettingKey.MANAGER_CAN_MANAGE_CONTENT: SettingSpec(
        control="toggle",
        label="Managers can edit website content and FAQ",
    ),
    SettingKey.MFA_REQUIRED_ROLES: SettingSpec(
        # A list of role names, so the editor picks roles rather than typing
        # the JSON the column happens to store.
        control="multi_choice",
        label="Roles requiring multi-factor authentication",
        choices=(
            ("admin", "Administrators"),
            ("manager", "Managers"),
            ("client", "Clients"),
        ),
        hint=(
            "Not yet enforced — the sign-in step arrives with the security "
            "hardening work. The setting exists so the decision is recorded."
        ),
    ),
    SettingKey.DOCUMENT_VERSIONING: SettingSpec(
        control="choice",
        label="When a document is re-uploaded",
        choices=(
            ("keep", "Keep previous versions"),
            ("overwrite", "Replace the previous version"),
        ),
        hint="Keeping versions is safer for tax records.",
    ),
    SettingKey.NOTIFY_ENQUIRY_RECIPIENTS: SettingSpec(
        control="email_list",
        label="Website enquiry alerts",
        hint=(
            "Who is emailed when someone submits the contact form. While this "
            "is empty, enquiries are still recorded in the Admin Portal but no "
            "email is sent."
        ),
    ),
    SettingKey.NOTIFY_DOCUMENT_RECIPIENTS: SettingSpec(
        control="email_list",
        label="Client document upload alerts",
        hint="Who is emailed when a client uploads a document.",
    ),
    SettingKey.SERVICE_SHORT_DESCRIPTION_MIN_WORDS: SettingSpec(
        control="number",
        label="Service description: suggested minimum",
        minimum=0,
        maximum=200,
        unit="words",
        hint="Guidance shown to editors. Never enforced.",
    ),
    SettingKey.SERVICE_SHORT_DESCRIPTION_MAX_WORDS: SettingSpec(
        control="number",
        label="Service description: suggested maximum",
        minimum=0,
        maximum=200,
        unit="words",
    ),
    SettingKey.WISE_PAYMENT_LINK_BASE_URL: SettingSpec(
        control="text",
        label="Wise Open Payment Link",
        hint=(
            "Copied from Payments → Payment Links in your Wise Business "
            "account. Amount, currency and invoice reference are appended "
            "automatically. Until this is set, Pay Now stays unavailable."
        ),
    ),
}

GROUP_LABELS: dict[str, str] = {
    "chatbot": "Smart AI",
    "accounts": "Accounts and access",
    "security": "Security",
    "documents": "Documents",
    "notifications": "Notifications",
    "content": "Website content",
    "payments": "Payments",
}
