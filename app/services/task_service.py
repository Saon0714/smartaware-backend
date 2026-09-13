"""Task workflow — spec Sections 5.3.B, 6.1 and 6.3."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.enums import TaskStatus, UserRole
from app.models.task import Task
from app.models.user import User
from app.services import audit_service, client_service
from app.services.audit_service import AuditAction


class TaskError(Exception):
    """Operation refused. The message is safe to show the caller."""


def create(
    db: Session,
    *,
    actor: User,
    client_id: uuid.UUID,
    title: str,
    **fields,
) -> Task:
    """Create a task, refusing if the client is not active.

    Section 6.2: while an account is on Hold the assigned Manager performs no
    work, and no new tasks are created.
    """
    client_service.assert_work_permitted(db, client_id)
    _validate_assignee(db, fields.get("assigned_manager_id"))

    task = Task(
        client_id=client_id,
        title=title,
        created_by_id=actor.id,
        **{k: v for k, v in fields.items() if v is not None},
    )
    db.add(task)
    db.flush()
    return task


def _validate_assignee(db: Session, manager_id: uuid.UUID | None) -> None:
    if manager_id is None:
        return
    manager = db.get(User, manager_id)
    if manager is None or manager.role not in (UserRole.MANAGER, UserRole.ADMIN):
        raise TaskError("Tasks can only be assigned to a manager or administrator.")
    if not manager.is_active:
        raise TaskError("That account is not active and cannot be assigned work.")


def update(db: Session, *, task: Task, changes: dict) -> Task:
    """Apply a progress update.

    Completion is refused here: Section 6.3 requires a note and a
    server-recorded timestamp, which only the completion path provides.
    Allowing status to be set to completed through a general update would be a
    way around both.
    """
    if changes.get("status") is TaskStatus.COMPLETED:
        raise TaskError("Use the complete action to finish a task — a completion note is required.")

    if task.completed_at is not None:
        raise TaskError("This task is complete. Reopen it before making changes.")

    client_service.assert_work_permitted(db, task.client_id)

    if "assigned_manager_id" in changes:
        _validate_assignee(db, changes["assigned_manager_id"])

    for field, value in changes.items():
        setattr(task, field, value)
    db.flush()
    return task


def complete(
    db: Session,
    *,
    task: Task,
    actor: User,
    note: str,
    ip_address: str | None = None,
) -> Task:
    """Mark a task complete — Section 6.3.

    The timestamp is taken here rather than accepted from the caller, which is
    what makes backdating impossible. Completion is audited because it is the
    moment a client is told work is finished.
    """
    if task.completed_at is not None:
        raise TaskError("This task is already complete.")

    client_service.assert_work_permitted(db, task.client_id)

    task.status = TaskStatus.COMPLETED
    task.completed_note = note
    task.completed_at = datetime.now(UTC)
    task.completed_by_id = actor.id

    audit_service.record(
        db,
        actor=actor,
        action=AuditAction.TASK_COMPLETED,
        entity_type="task",
        entity_id=task.id,
        new_value={
            "status": TaskStatus.COMPLETED.value,
            "completed_at": task.completed_at.isoformat(),
            "client_id": str(task.client_id),
        },
        reason=note,
        ip_address=ip_address,
    )
    db.flush()
    return task


def reopen(db: Session, *, task: Task, actor: User, reason: str | None = None) -> Task:
    """Undo a completion.

    The original note and timestamp are cleared rather than kept, because a
    task that is open again has not been completed — leaving them would make
    the client's view contradict itself. The audit entry preserves what
    happened.
    """
    if task.completed_at is None:
        raise TaskError("This task is not complete.")

    previous = {
        "completed_at": task.completed_at.isoformat(),
        "completed_note": task.completed_note,
    }
    task.status = TaskStatus.IN_PROGRESS
    task.completed_at = None
    task.completed_note = None
    task.completed_by_id = None

    audit_service.record(
        db,
        actor=actor,
        action="task.reopened",
        entity_type="task",
        entity_id=task.id,
        old_value=previous,
        reason=reason,
    )
    db.flush()
    return task


def archive(db: Session, *, task: Task, actor: User, ip_address: str | None = None) -> Task:
    """Admin's delete.

    Implemented as an archive: a task is the record that work was done for a
    client, and destroying it would remove evidence relevant to billing or a
    later dispute. Section 9 also asks for deletions to be auditable, which a
    vanished row cannot be.
    """
    if task.is_archived:
        raise TaskError("This task is already archived.")

    task.is_archived = True
    audit_service.record(
        db,
        actor=actor,
        action=AuditAction.TASK_DELETED,
        entity_type="task",
        entity_id=task.id,
        old_value={"title": task.title, "client_id": str(task.client_id)},
        ip_address=ip_address,
    )
    db.flush()
    return task


def restore(db: Session, *, task: Task, actor: User) -> Task:
    if not task.is_archived:
        raise TaskError("This task is not archived.")
    task.is_archived = False
    audit_service.record(
        db, actor=actor, action="task.restored", entity_type="task", entity_id=task.id
    )
    db.flush()
    return task


def is_overdue(task: Task, today: date | None = None) -> bool:
    if task.due_date is None or task.completed_at is not None:
        return False
    if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
        return False
    return task.due_date < (today or datetime.now(UTC).date())


def counts_for(db: Session, scope, client_id: uuid.UUID | None = None) -> dict:
    """Summary counts for a dashboard, honouring the caller's scope."""
    stmt = select(Task).where(Task.is_archived.is_(False))
    stmt = scope.apply(stmt, Task.client_id)
    if client_id is not None:
        stmt = stmt.where(Task.client_id == client_id)

    tasks = list(db.execute(stmt).scalars())
    return {
        "total": len(tasks),
        "pending": sum(1 for t in tasks if t.status is TaskStatus.PENDING),
        "in_progress": sum(1 for t in tasks if t.status is TaskStatus.IN_PROGRESS),
        "completed": sum(1 for t in tasks if t.status is TaskStatus.COMPLETED),
        "cancelled": sum(1 for t in tasks if t.status is TaskStatus.CANCELLED),
        "overdue": sum(1 for t in tasks if is_overdue(t)),
    }


def client_of(db: Session, task: Task) -> Client | None:
    return db.get(Client, task.client_id)
