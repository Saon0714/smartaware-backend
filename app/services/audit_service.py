"""Audit trail — spec Section 9.

Section 9 asks for audit logging of task completions, document access and
manager reassignments. Those are the actions where "who changed this, and
when" is a question someone will eventually need answered: a client disputing
that work was completed, or a manager asking why an account left their list.

Entries are written in the same transaction as the change they describe, so an
audited action cannot commit without its record.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.user import User


class AuditAction:
    """Canonical action names, so reports filter on a constant not a typo."""

    CLIENT_CREATED = "client.created"
    CLIENT_UPDATED = "client.updated"
    CLIENT_STATUS_CHANGED = "client.status_changed"
    CLIENT_MANAGER_ASSIGNED = "client.manager_assigned"
    TASK_COMPLETED = "task.completed"
    TASK_DELETED = "task.deleted"
    DOCUMENT_DOWNLOADED = "document.downloaded"
    INVOICE_RECONCILED = "invoice.reconciled"
    USER_DEACTIVATED = "user.deactivated"


def record(
    db: Session,
    *,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Add an audit entry. Flushed, not committed — the caller's transaction
    decides whether both the change and its record survive."""
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        ip_address=ip_address,
    )
    db.add(entry)
    db.flush()
    return entry
