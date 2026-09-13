"""The notification service — spec Section 7.

One entry point, `notify`, for every outbound message. Section 7 asks for this
explicitly: "built on a shared, reusable notification service (not one-off email
calls scattered through the codebase) so recipients, templates, and triggers can
be managed centrally."

Recipients are resolved from the `settings` table at send time, so SmartAWARE
changes who gets notified from the Admin Portal rather than through a deploy.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_service import get_setting
from app.models.client import Client
from app.models.enums import UserRole
from app.models.user import User
from app.services.notification.backends import get_backend
from app.services.notification.events import (
    EVENT_AUDIENCE,
    TEAM_RECIPIENT_SETTING,
    Audience,
    NotificationEvent,
)
from app.services.notification.templates import TemplateError, render

logger = logging.getLogger(__name__)


def _team_recipients(db: Session, event: NotificationEvent) -> list[str]:
    key = TEAM_RECIPIENT_SETTING.get(event)
    if key is None:
        return []
    configured = get_setting(db, key, []) or []
    return [address for address in configured if isinstance(address, str) and address]


def _admin_and_manager(db: Session, client_id: uuid.UUID | None) -> list[str]:
    recipients: list[str] = []

    admins = db.execute(
        select(User.email).where(User.role == UserRole.ADMIN, User.is_active.is_(True))
    ).scalars()
    recipients.extend(admins)

    if client_id is not None:
        client = db.get(Client, client_id)
        if client and client.assigned_manager_id:
            manager = db.get(User, client.assigned_manager_id)
            if manager and manager.is_active:
                recipients.append(manager.email)

    return recipients


def _client_recipient(db: Session, client_id: uuid.UUID | None) -> list[str]:
    if client_id is None:
        return []
    client = db.get(Client, client_id)
    if client is None:
        return []
    user = db.get(User, client.user_id)
    return [user.email] if user and user.is_active else []


def resolve_recipients(
    db: Session,
    event: NotificationEvent,
    *,
    client_id: uuid.UUID | None = None,
    to: str | list[str] | None = None,
) -> list[str]:
    """Work out who receives this event. Never hardcoded at the call site."""
    audience = EVENT_AUDIENCE[event]

    if audience is Audience.EXPLICIT:
        if to is None:
            return []
        return [to] if isinstance(to, str) else list(to)
    if audience is Audience.SMARTAWARE_TEAM:
        return _team_recipients(db, event)
    if audience is Audience.ADMIN_AND_ASSIGNED_MANAGER:
        return _admin_and_manager(db, client_id)
    if audience is Audience.CLIENT:
        return _client_recipient(db, client_id)
    return []


@dataclass(frozen=True)
class PreparedMessage:
    """A notification with its recipients and wording already resolved.

    Everything needing the database is done up front, so dispatch is pure I/O.
    That matters for deferred sending: the background task neither opens a
    second session nor races the transaction that triggered it, and moving it
    onto Celery later means serialising this object rather than re-querying.
    """

    event: NotificationEvent
    recipients: tuple[str, ...]
    subject: str
    body: str


def prepare(
    db: Session,
    event: NotificationEvent,
    context: dict[str, object],
    *,
    client_id: uuid.UUID | None = None,
    to: str | list[str] | None = None,
) -> PreparedMessage | None:
    """Resolve recipients and render the message, or return None if there is
    nothing to send. Never raises into the caller."""
    try:
        recipients = resolve_recipients(db, event, client_id=client_id, to=to)
    except Exception:
        logger.exception("Could not resolve recipients for %s", event)
        return None

    if not recipients:
        # Expected while the notify_* settings are still empty. Logged at
        # warning so it is visible rather than silently dropped.
        logger.warning(
            "No recipients configured for %s — nothing sent. "
            "Set the relevant notify_* setting in the Admin Portal.",
            event,
        )
        return None

    try:
        subject, body = render(event, context)
    except TemplateError:
        logger.exception("Could not render template for %s", event)
        return None

    return PreparedMessage(
        event=event,
        # De-duplicated, order preserved.
        recipients=tuple(dict.fromkeys(recipients)),
        subject=subject,
        body=body,
    )


def dispatch(message: PreparedMessage | None) -> list[str]:
    """Deliver a prepared message. Returns the addresses that accepted it.

    Never raises. A notification failing must not roll back the action that
    triggered it — an enquiry stored but whose alert bounced is a far better
    outcome than losing the enquiry.
    """
    if message is None:
        return []

    backend = get_backend()
    delivered: list[str] = []
    for address in message.recipients:
        try:
            backend.send(to=address, subject=message.subject, body=message.body)
            delivered.append(address)
        except Exception:
            # One bad address must not stop the rest.
            logger.exception("Failed to send %s to %s", message.event, address)
    return delivered


def notify(
    db: Session,
    event: NotificationEvent,
    context: dict[str, object],
    *,
    client_id: uuid.UUID | None = None,
    to: str | list[str] | None = None,
) -> list[str]:
    """Prepare and send in one step, for callers that are not deferring."""
    return dispatch(prepare(db, event, context, client_id=client_id, to=to))
