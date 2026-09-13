"""The notification catalogue — spec Section 7.

Every notification the system sends is named here, with who receives it. Having
one enumeration rather than scattered `send_email` calls is what makes it
possible to answer "what do we send, and to whom" without reading the codebase.

Events for features that arrive in later chunks are declared now so the routing
rules live in one place; they simply have no caller yet.
"""

import enum


class Audience(enum.StrEnum):
    """Who a notification goes to. Resolved at send time, never hardcoded."""

    #: Addresses from the `notify_*` settings, editable in the Admin Portal.
    SMARTAWARE_TEAM = "smartaware_team"
    #: The client the event concerns.
    CLIENT = "client"
    #: Admin, plus the client's assigned manager when there is one.
    ADMIN_AND_ASSIGNED_MANAGER = "admin_and_assigned_manager"
    #: A single address supplied by the caller (an invited person, say).
    EXPLICIT = "explicit"


class NotificationEvent(enum.StrEnum):
    # Live now
    INVITE_SENT = "invite_sent"
    ENQUIRY_SUBMITTED = "enquiry_submitted"

    # Declared for later chunks so the routing table stays in one place.
    CLIENT_DOCUMENT_UPLOADED = "client_document_uploaded"
    CLIENT_INVOICE_UPLOADED = "client_invoice_uploaded"
    SMARTAWARE_DOCUMENT_UPLOADED = "smartaware_document_uploaded"
    TASK_COMPLETED = "task_completed"
    PAYMENT_MADE = "payment_made"


#: Section 7's table, as data.
EVENT_AUDIENCE: dict[NotificationEvent, Audience] = {
    NotificationEvent.INVITE_SENT: Audience.EXPLICIT,
    NotificationEvent.ENQUIRY_SUBMITTED: Audience.SMARTAWARE_TEAM,
    NotificationEvent.CLIENT_DOCUMENT_UPLOADED: Audience.SMARTAWARE_TEAM,
    # More specific than a general upload (Section 5.3.D).
    NotificationEvent.CLIENT_INVOICE_UPLOADED: Audience.ADMIN_AND_ASSIGNED_MANAGER,
    NotificationEvent.SMARTAWARE_DOCUMENT_UPLOADED: Audience.CLIENT,
    NotificationEvent.TASK_COMPLETED: Audience.CLIENT,
    NotificationEvent.PAYMENT_MADE: Audience.SMARTAWARE_TEAM,
}

#: Which setting holds the recipient list for team-wide notifications.
TEAM_RECIPIENT_SETTING: dict[NotificationEvent, str] = {
    NotificationEvent.ENQUIRY_SUBMITTED: "notify_enquiry_recipients",
    NotificationEvent.CLIENT_DOCUMENT_UPLOADED: "notify_document_recipients",
    NotificationEvent.PAYMENT_MADE: "notify_document_recipients",
}
