"""Staff task management — spec Sections 6.1 and 6.3.

Permissions are declared per endpoint from the matrix rather than checked
inline. The one that matters most is deletion: Section 6.2 calls it out as a
privilege-escalation risk, so a Manager is refused by the permission layer and
not merely by a hidden button.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import (
    CallerClientScope,
    CurrentUser,
    DbSession,
    require_permission,
)
from app.core.permissions import Permission
from app.core.rate_limit import client_ip
from app.models.client import Client
from app.models.enums import TaskStatus
from app.models.service import ServiceCategory
from app.models.task import Task
from app.models.user import User
from app.schemas.task import (
    PersonSummary,
    TaskCompleteRequest,
    TaskCounts,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)
from app.services import task_service
from app.services.client_service import ClientError
from app.services.notification import NotificationEvent, dispatch, prepare

router = APIRouter(prefix="/admin", tags=["admin-tasks"])

_can_view = Depends(require_permission(Permission.TASK_VIEW))
_can_create = Depends(require_permission(Permission.TASK_CREATE))
_can_update = Depends(require_permission(Permission.TASK_UPDATE))
_can_complete = Depends(require_permission(Permission.TASK_COMPLETE))
#: Admin only. Absent from the Manager grant in core/permissions.py.
_can_delete = Depends(require_permission(Permission.TASK_DELETE))


def _person(user: User | None) -> PersonSummary | None:
    return PersonSummary.model_validate(user) if user else None


def _serialise(db: Session, task: Task) -> dict:
    client = db.get(Client, task.client_id)
    category = (
        db.get(ServiceCategory, task.service_category_id) if task.service_category_id else None
    )
    return {
        "id": task.id,
        "client_id": task.client_id,
        "client_ref": client.client_ref if client else "",
        "client_company_name": client.company_name if client else None,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "due_date": task.due_date,
        "service_category_id": task.service_category_id,
        "service_category_name": category.name if category else None,
        "service_subcategory_id": task.service_subcategory_id,
        "assigned_manager": _person(
            db.get(User, task.assigned_manager_id) if task.assigned_manager_id else None
        ),
        "created_by": _person(db.get(User, task.created_by_id) if task.created_by_id else None),
        "completed_by": _person(
            db.get(User, task.completed_by_id) if task.completed_by_id else None
        ),
        "completed_note": task.completed_note,
        "completed_at": task.completed_at,
        "is_archived": task.is_archived,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _load(db: Session, scope, task_id: uuid.UUID) -> Task:
    """Fetch a task the caller may see.

    Out of scope reads as missing, matching the client endpoints: confirming a
    task exists would leak which clients a manager is not assigned to.
    """
    task = db.get(Task, task_id)
    if task is None or not scope.allows(task.client_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return task


@router.get("/tasks", response_model=list[TaskOut], dependencies=[_can_view], name="list")
def list_tasks(
    db: DbSession,
    scope: CallerClientScope,
    client_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[TaskStatus | None, Query(alias="status")] = None,
    assigned_to: Annotated[uuid.UUID | None, Query()] = None,
    overdue: Annotated[bool, Query()] = False,
    include_archived: Annotated[bool, Query()] = False,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> Any:
    stmt = select(Task).order_by(Task.due_date.is_(None), Task.due_date, Task.created_at.desc())
    stmt = scope.apply(stmt, Task.client_id)

    if not include_archived:
        stmt = stmt.where(Task.is_archived.is_(False))
    if client_id is not None:
        stmt = stmt.where(Task.client_id == client_id)
    if status_filter is not None:
        stmt = stmt.where(Task.status == status_filter)
    if assigned_to is not None:
        stmt = stmt.where(Task.assigned_manager_id == assigned_to)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(or_(Task.title.ilike(pattern), Task.description.ilike(pattern)))

    tasks = list(db.execute(stmt).scalars())
    if overdue:
        tasks = [t for t in tasks if task_service.is_overdue(t)]
    return [_serialise(db, t) for t in tasks]


@router.get("/tasks/counts", response_model=TaskCounts, dependencies=[_can_view], name="counts")
def task_counts(
    db: DbSession,
    scope: CallerClientScope,
    client_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Any:
    return task_service.counts_for(db, scope, client_id)


@router.get("/tasks/{task_id}", response_model=TaskOut, dependencies=[_can_view], name="get")
def get_task(task_id: uuid.UUID, db: DbSession, scope: CallerClientScope) -> Any:
    return _serialise(db, _load(db, scope, task_id))


@router.post(
    "/tasks",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_can_create],
    name="create",
)
def create_task(
    payload: TaskCreate, user: CurrentUser, db: DbSession, scope: CallerClientScope
) -> Any:
    if not scope.allows(payload.client_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found.")

    data = payload.model_dump(exclude={"client_id", "title"})
    try:
        task = task_service.create(
            db, actor=user, client_id=payload.client_id, title=payload.title, **data
        )
    except (ClientError, task_service.TaskError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.commit()
    db.refresh(task)
    return _serialise(db, task)


@router.patch("/tasks/{task_id}", response_model=TaskOut, dependencies=[_can_update], name="update")
def update_task(
    task_id: uuid.UUID, payload: TaskUpdate, db: DbSession, scope: CallerClientScope
) -> Any:
    task = _load(db, scope, task_id)
    try:
        task_service.update(db, task=task, changes=payload.model_dump(exclude_unset=True))
    except (ClientError, task_service.TaskError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.commit()
    db.refresh(task)
    return _serialise(db, task)


@router.post(
    "/tasks/{task_id}/complete",
    response_model=TaskOut,
    dependencies=[_can_complete],
    name="complete",
)
def complete_task(
    task_id: uuid.UUID,
    payload: TaskCompleteRequest,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    scope: CallerClientScope,
) -> Any:
    """Section 6.3: note required, timestamp server-side, client notified."""
    task = _load(db, scope, task_id)
    try:
        task_service.complete(
            db, task=task, actor=user, note=payload.note, ip_address=client_ip(request)
        )
    except (ClientError, task_service.TaskError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    client = task_service.client_of(db, task)
    message = prepare(
        db,
        NotificationEvent.TASK_COMPLETED,
        {
            "client_name": (client.company_name if client else None) or "there",
            "task_title": task.title,
            "completed_at": task.completed_at.strftime("%d %B %Y"),
            "completion_note": payload.note,
            "portal_url": f"{settings.FRONTEND_BASE_URL.rstrip('/')}/portal/tasks",
        },
        client_id=task.client_id,
    )
    db.commit()
    # Sent after the response so a mail failure cannot undo a completion.
    dispatch(message)

    db.refresh(task)
    return _serialise(db, task)


@router.post(
    "/tasks/{task_id}/reopen",
    response_model=TaskOut,
    dependencies=[_can_update],
    name="reopen",
)
def reopen_task(
    task_id: uuid.UUID, user: CurrentUser, db: DbSession, scope: CallerClientScope
) -> Any:
    task = _load(db, scope, task_id)
    try:
        task_service.reopen(db, task=task, actor=user)
    except task_service.TaskError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(task)
    return _serialise(db, task)


@router.delete(
    "/tasks/{task_id}", response_model=TaskOut, dependencies=[_can_delete], name="delete"
)
def delete_task(
    task_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    scope: CallerClientScope,
) -> Any:
    """Admin only (Section 6.1). Archives rather than destroys — see
    task_service.archive for why."""
    task = _load(db, scope, task_id)
    try:
        task_service.archive(db, task=task, actor=user, ip_address=client_ip(request))
    except task_service.TaskError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(task)
    return _serialise(db, task)


@router.post(
    "/tasks/{task_id}/restore",
    response_model=TaskOut,
    dependencies=[_can_delete],
    name="restore",
)
def restore_task(
    task_id: uuid.UUID, user: CurrentUser, db: DbSession, scope: CallerClientScope
) -> Any:
    task = _load(db, scope, task_id)
    try:
        task_service.restore(db, task=task, actor=user)
    except task_service.TaskError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(task)
    return _serialise(db, task)
