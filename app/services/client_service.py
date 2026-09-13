"""Client account management — spec Section 6.2."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.enums import ClientStatus, UserRole
from app.models.user import User
from app.services import audit_service
from app.services.audit_service import AuditAction


class ClientError(Exception):
    """Operation refused. The message is safe to show the caller."""


def assert_work_permitted(db: Session, client_id: uuid.UUID) -> None:
    """Refuse work for a client who is not Active.

    Section 6.2: while an account is on Hold the assigned Manager performs no
    work — no new tasks, none marked complete. Deactive is terminal but blocks
    the same actions. Enforced here rather than in the UI, and called from the
    task endpoints when they arrive in the next chunk, so a direct API call
    cannot bypass it.
    """
    client = db.get(Client, client_id)
    if client is None:
        raise ClientError("Client not found.")

    if client.status is ClientStatus.HOLD:
        raise ClientError(
            "This client is on hold. No work can be recorded until an "
            "administrator sets the account back to active."
        )
    if client.status is ClientStatus.DEACTIVE:
        raise ClientError("This client account is deactivated. No further work can be recorded.")


def list_staff(db: Session, *, managers_only: bool = False) -> list[User]:
    """Staff eligible for assignment.

    Inactive users are excluded: Section 6.2's intent is that work is assigned
    to someone who can act on it, and an inactive account cannot sign in.
    """
    roles = [UserRole.MANAGER] if managers_only else [UserRole.MANAGER, UserRole.ADMIN]
    return list(
        db.execute(
            select(User)
            .where(User.role.in_(roles), User.is_active.is_(True))
            .order_by(User.full_name, User.email)
        ).scalars()
    )


def set_status(
    db: Session,
    *,
    client: Client,
    status: ClientStatus,
    note: str,
    actor: User,
    ip_address: str | None = None,
) -> Client:
    """Change an account's status, recording who did it and why."""
    if client.status is status:
        raise ClientError(f"This account is already {status.value}.")

    previous = client.status
    client.status = status
    client.status_note = note

    # Hold and Deactive both block login. Bumping the token version ends any
    # session already open, so the change takes effect immediately rather than
    # when the current access token happens to expire.
    if status in (ClientStatus.HOLD, ClientStatus.DEACTIVE):
        user = db.get(User, client.user_id)
        if user is not None:
            user.token_version += 1

    audit_service.record(
        db,
        actor=actor,
        action=AuditAction.CLIENT_STATUS_CHANGED,
        entity_type="client",
        entity_id=client.id,
        old_value={"status": previous.value},
        new_value={"status": status.value},
        reason=note,
        ip_address=ip_address,
    )
    db.flush()
    return client


def assign_manager(
    db: Session,
    *,
    client: Client,
    manager_id: uuid.UUID | None,
    actor: User,
    note: str | None = None,
    ip_address: str | None = None,
) -> Client:
    """Assign or clear the account's manager.

    Reassignment changes who can see this client's data, so Section 9 lists it
    among the actions worth auditing.
    """
    manager: User | None = None
    if manager_id is not None:
        manager = db.get(User, manager_id)
        if manager is None or manager.role is not UserRole.MANAGER:
            raise ClientError("That user is not a manager.")
        if not manager.is_active:
            raise ClientError("That manager's account is not active.")

    previous_id = client.assigned_manager_id
    if previous_id == manager_id:
        raise ClientError("That manager is already assigned to this client.")

    previous = db.get(User, previous_id) if previous_id else None
    client.assigned_manager_id = manager_id

    audit_service.record(
        db,
        actor=actor,
        action=AuditAction.CLIENT_MANAGER_ASSIGNED,
        entity_type="client",
        entity_id=client.id,
        old_value={
            "manager_id": str(previous_id) if previous_id else None,
            "manager_email": previous.email if previous else None,
        },
        new_value={
            "manager_id": str(manager_id) if manager_id else None,
            "manager_email": manager.email if manager else None,
        },
        reason=note,
        ip_address=ip_address,
    )
    db.flush()
    return client
