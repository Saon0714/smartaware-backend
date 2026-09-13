"""Client portal: work status — spec Section 5.3.B.

Read-only, by design and by construction. There is no create, update, complete
or delete endpoint here at all, so a client cannot perform those actions even
by calling the API directly — the routes do not exist, and the staff routes
that do are behind permissions no client holds.

Section 5.3.B also states that a status change only appears here once staff
have recorded it, which follows naturally: this reads the same rows the staff
endpoints write.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import CallerClientScope, DbSession
from app.models.enums import TaskStatus
from app.models.service import ServiceCategory
from app.models.task import Task
from app.models.user import User
from app.schemas.task import ClientTaskOut, TaskCounts
from app.services import task_service

router = APIRouter(prefix="/portal", tags=["portal-tasks"])


def _serialise(db: Session, task: Task) -> dict:
    category = (
        db.get(ServiceCategory, task.service_category_id) if task.service_category_id else None
    )
    completed_by = db.get(User, task.completed_by_id) if task.completed_by_id else None
    return {
        "id": task.id,
        "client_id": task.client_id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "due_date": task.due_date,
        "service_category_id": task.service_category_id,
        "service_category_name": category.name if category else None,
        "service_subcategory_id": task.service_subcategory_id,
        "completed_note": task.completed_note,
        "completed_at": task.completed_at,
        # A name, not an account: who did the work is useful context, but the
        # client has no business with SmartAWARE's internal user records.
        "completed_by_name": (
            (completed_by.full_name or completed_by.email) if completed_by else None
        ),
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


@router.get("/tasks", response_model=list[ClientTaskOut], summary="My tasks")
def my_tasks(
    db: DbSession,
    scope: CallerClientScope,
    status_filter: Annotated[TaskStatus | None, Query(alias="status")] = None,
) -> Any:
    stmt = (
        select(Task)
        .where(Task.is_archived.is_(False))
        .order_by(Task.due_date.is_(None), Task.due_date, Task.created_at.desc())
    )
    # The scope makes this the caller's own records and nobody else's, even if
    # a client_id were somehow supplied.
    stmt = scope.apply(stmt, Task.client_id)
    if status_filter is not None:
        stmt = stmt.where(Task.status == status_filter)

    return [_serialise(db, t) for t in db.execute(stmt).scalars()]


@router.get("/tasks/counts", response_model=TaskCounts, summary="My task counts")
def my_task_counts(db: DbSession, scope: CallerClientScope) -> Any:
    return task_service.counts_for(db, scope)


@router.get("/tasks/{task_id}", response_model=ClientTaskOut, summary="One of my tasks")
def my_task(task_id: uuid.UUID, db: DbSession, scope: CallerClientScope) -> Any:
    task = db.get(Task, task_id)
    if task is None or task.is_archived or not scope.allows(task.client_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return _serialise(db, task)
