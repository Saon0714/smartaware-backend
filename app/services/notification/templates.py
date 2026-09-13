"""Message templates.

Kept in one module so wording is reviewed in one place rather than inlined at
each call site. Subjects and bodies are plain text: these are transactional
notifications, and plain text renders identically everywhere without a fallback.

Placeholders are filled from the context dict passed to `notify`. A missing key
raises rather than silently sending "{client_name}" to a real person.
"""

from dataclasses import dataclass

from app.services.notification.events import NotificationEvent


@dataclass(frozen=True)
class Template:
    subject: str
    body: str


TEMPLATES: dict[NotificationEvent, Template] = {
    # `portal_name` rather than a fixed "Client Portal": the same invitation
    # creates staff accounts too, and telling a new Manager they are being given
    # a client portal account is both wrong and confusing on their first contact
    # with the system.
    NotificationEvent.INVITE_SENT: Template(
        subject="You have been invited to the SmartAWARE {portal_name}",
        body=(
            "You have been invited to create a SmartAWARE {portal_name} account.\n\n"
            "Set up your account:\n{invite_url}\n\n"
            "This link can be used once and expires in {expiry_days} days.\n\n"
            "If you were not expecting this invitation, you can ignore this email."
        ),
    ),
    NotificationEvent.ENQUIRY_SUBMITTED: Template(
        subject="New website enquiry from {name}",
        body=(
            "A new enquiry has been submitted through the SmartAWARE website.\n\n"
            "{summary}\n\n"
            "View it in the Admin Portal:\n{admin_url}"
        ),
    ),
    NotificationEvent.TASK_COMPLETED: Template(
        subject="A task has been completed: {task_title}",
        body=(
            "Hello {client_name},\n\n"
            "SmartAWARE has completed the following task:\n\n"
            "{task_title}\n"
            "Completed: {completed_at}\n\n"
            "{completion_note}\n\n"
            "You can view the details in your portal:\n{portal_url}"
        ),
    ),
    NotificationEvent.CLIENT_DOCUMENT_UPLOADED: Template(
        subject="{client_name} uploaded a document",
        body=(
            "{client_name} has uploaded a document to the Client Portal.\n\n"
            "File: {file_name}\n\n"
            "View it in the Admin Portal:\n{admin_url}"
        ),
    ),
    NotificationEvent.CLIENT_INVOICE_UPLOADED: Template(
        subject="{client_name} uploaded a payment receipt",
        body=(
            "{client_name} has uploaded a payment receipt for reconciliation.\n\n"
            "File: {file_name}\n"
            "Invoice: {invoice_reference}\n\n"
            "View it in the Admin Portal:\n{admin_url}"
        ),
    ),
    NotificationEvent.SMARTAWARE_DOCUMENT_UPLOADED: Template(
        subject="SmartAWARE has shared a document with you",
        body=(
            "Hello {client_name},\n\n"
            "SmartAWARE has uploaded a document to your portal.\n\n"
            "File: {file_name}\n\n"
            "View it here:\n{portal_url}"
        ),
    ),
    NotificationEvent.PAYMENT_MADE: Template(
        subject="Payment received from {client_name}",
        body=(
            "{client_name} has indicated a payment for invoice "
            "{invoice_reference}.\n\n"
            "This still requires reconciliation against the Wise account before "
            "the invoice is marked as paid.\n\n"
            "View it in the Admin Portal:\n{admin_url}"
        ),
    ),
}


class TemplateError(Exception):
    """A template referenced a value the caller did not supply."""


def render(event: NotificationEvent, context: dict[str, object]) -> tuple[str, str]:
    template = TEMPLATES.get(event)
    if template is None:
        raise TemplateError(f"No template defined for {event}")
    try:
        return (
            template.subject.format(**context),
            template.body.format(**context),
        )
    except KeyError as exc:
        raise TemplateError(f"Template for {event} needs {exc} but it was not provided.") from exc
