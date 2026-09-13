"""Enumerations shared across models.

Stored as native Postgres enums. Values that SmartAWARE may want to extend
without a deploy (service categories, regions, form fields, wizard questions)
are deliberately NOT enums — they are rows in tables.
"""

import enum


class UserRole(enum.StrEnum):
    ADMIN = "admin"
    MANAGER = "manager"
    CLIENT = "client"


class ClientStatus(enum.StrEnum):
    """Spec Section 6.2.

    HOLD and DEACTIVE block login identically; they differ only in business
    meaning (paused vs. ended), which Admin uses for their own reporting.
    """

    ACTIVE = "active"
    HOLD = "hold"
    DEACTIVE = "deactive"


class InviteStatus(enum.StrEnum):
    PENDING = "pending"
    USED = "used"
    REVOKED = "revoked"
    EXPIRED = "expired"


class TaskStatus(enum.StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DocumentDirection(enum.StrEnum):
    CLIENT_TO_SMARTAWARE = "client_to_smartaware"
    SMARTAWARE_TO_CLIENT = "smartaware_to_client"


class DocumentType(enum.StrEnum):
    GENERAL = "general"
    INVOICE = "invoice"


class InvoiceStatus(enum.StrEnum):
    UNPAID = "unpaid"
    PAID = "paid"
    CANCELLED = "cancelled"


class ReconciliationMethod(enum.StrEnum):
    """Manual today (spec 12.4). The column exists so an automated Wise
    reconciliation can be introduced later without a schema change."""

    MANUAL = "manual"
    AUTOMATED = "automated"


class ChatSurface(enum.StrEnum):
    PUBLIC = "public"
    PORTAL = "portal"


class ChatRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class FormFieldType(enum.StrEnum):
    TEXT = "text"
    TEXTAREA = "textarea"
    EMAIL = "email"
    PHONE = "phone"
    NUMBER = "number"
    DATE = "date"
    SELECT = "select"
    MULTISELECT = "multiselect"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    COUNTRY = "country"


class SettingValueType(enum.StrEnum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    JSON = "json"
