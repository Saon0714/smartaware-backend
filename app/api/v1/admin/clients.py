"""Admin: client accounts — spec Section 6.2.

Every listing is constrained by the caller's client scope, so a Manager sees
only the accounts they are assigned (or all, if SmartAWARE enables that
setting) without each handler re-deriving the rule.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.deps import (
    CallerClientScope,
    DbSession,
    RequireAdmin,
    require_permission,
)
from app.core.permissions import Permission
from app.core.rate_limit import client_ip
from app.models.audit import AuditLog
from app.models.client import Client
from app.models.enums import ClientStatus
from app.models.user import User
from app.schemas.client import (
    AuditEntryOut,
    ClientDetail,
    ClientSummary,
    ClientUpdate,
    ManagerAssignmentRequest,
    StaffSummary,
    StatusChangeRequest,
)
from app.services import client_service

router = APIRouter(prefix="/admin", tags=["admin-clients"])

_can_view = Depends(require_permission(Permission.CLIENT_VIEW))
_can_update = Depends(require_permission(Permission.CLIENT_UPDATE))


def _summary(client: Client, user: User, manager: User | None) -> dict:
    return {
        "id": client.id,
        "client_ref": client.client_ref,
        "company_name": client.company_name,
        "owner_name": client.owner_name,
        "contact_email": client.contact_email,
        "country": client.country,
        "status": client.status,
        "onboarding_completed_at": client.onboarding_completed_at,
        "created_at": client.created_at,
        "user_id": user.id,
        "user_email": user.email,
        "user_is_active": user.is_active,
        "last_login_at": user.last_login_at,
        "assigned_manager": StaffSummary.model_validate(manager) if manager else None,
    }


def _load(db: Session, scope, client_id: uuid.UUID) -> tuple[Client, User, User | None]:
    """Fetch a client the caller is permitted to see.

    A client outside the caller's scope is reported as missing rather than
    forbidden: confirming that an account exists would leak the client list to
    a manager who is not assigned to it.
    """
    if not scope.allows(client_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found.")

    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found.")

    user = db.get(User, client.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found.")

    manager = db.get(User, client.assigned_manager_id) if client.assigned_manager_id else None
    return client, user, manager


@router.get(
    "/clients",
    response_model=list[ClientSummary],
    dependencies=[_can_view],
    name="list",
)
def list_clients(
    db: DbSession,
    scope: CallerClientScope,
    status_filter: Annotated[ClientStatus | None, Query(alias="status")] = None,
    manager_id: Annotated[uuid.UUID | None, Query()] = None,
    unassigned: Annotated[bool, Query()] = False,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> Any:
    stmt = (
        select(Client, User)
        .join(User, User.id == Client.user_id)
        .order_by(Client.created_at.desc())
    )
    stmt = scope.apply(stmt, Client.id)

    if status_filter is not None:
        stmt = stmt.where(Client.status == status_filter)
    if unassigned:
        stmt = stmt.where(Client.assigned_manager_id.is_(None))
    elif manager_id is not None:
        stmt = stmt.where(Client.assigned_manager_id == manager_id)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Client.company_name.ilike(pattern),
                Client.owner_name.ilike(pattern),
                Client.client_ref.ilike(pattern),
                User.email.ilike(pattern),
            )
        )

    rows = db.execute(stmt).all()
    managers = {
        m.id: m
        for m in db.execute(
            select(User).where(
                User.id.in_([c.assigned_manager_id for c, _ in rows if c.assigned_manager_id])
            )
        ).scalars()
    }
    return [
        _summary(client, user, managers.get(client.assigned_manager_id)) for client, user in rows
    ]


@router.get(
    "/clients/{client_id}",
    response_model=ClientDetail,
    dependencies=[_can_view],
    name="get",
)
def get_client(client_id: uuid.UUID, db: DbSession, scope: CallerClientScope) -> Any:
    client, user, manager = _load(db, scope, client_id)
    return {
        **_summary(client, user, manager),
        "company_registration_number": client.company_registration_number,
        "registration_date": client.registration_date,
        "address_line1": client.address_line1,
        "address_line2": client.address_line2,
        "city": client.city,
        "region_or_county": client.region_or_county,
        "postcode": client.postcode,
        "contact_phone": client.contact_phone,
        "status_note": client.status_note,
        "extra": client.extra or {},
    }


@router.patch(
    "/clients/{client_id}",
    response_model=ClientDetail,
    dependencies=[_can_update],
    name="update",
)
def update_client(
    client_id: uuid.UUID,
    payload: ClientUpdate,
    db: DbSession,
    scope: CallerClientScope,
) -> Any:
    client, _user, _manager = _load(db, scope, client_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(client, field, value)
    db.commit()
    return get_client(client_id, db, scope)


@router.post(
    "/clients/{client_id}/status",
    response_model=ClientDetail,
    name="set_status",
)
def set_status(
    client_id: uuid.UUID,
    payload: StatusChangeRequest,
    request: Request,
    admin: RequireAdmin,
    db: DbSession,
    scope: CallerClientScope,
) -> Any:
    """Admin only.

    Section 6.2 places this entirely at Admin's discretion, following a
    conversation with the client — it is never automated and never delegated.
    """
    client, _user, _manager = _load(db, scope, client_id)
    try:
        client_service.set_status(
            db,
            client=client,
            status=payload.status,
            note=payload.note,
            actor=admin,
            ip_address=client_ip(request),
        )
    except client_service.ClientError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return get_client(client_id, db, scope)


@router.post(
    "/clients/{client_id}/manager",
    response_model=ClientDetail,
    name="assign_manager",
)
def assign_manager(
    client_id: uuid.UUID,
    payload: ManagerAssignmentRequest,
    request: Request,
    admin: RequireAdmin,
    db: DbSession,
    scope: CallerClientScope,
) -> Any:
    """Admin only — Section 6.1 gives Managers no say in their own allocation."""
    client, _user, _manager = _load(db, scope, client_id)
    try:
        client_service.assign_manager(
            db,
            client=client,
            manager_id=payload.manager_id,
            actor=admin,
            note=payload.note,
            ip_address=client_ip(request),
        )
    except client_service.ClientError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return get_client(client_id, db, scope)


@router.get(
    "/staff",
    response_model=list[StaffSummary],
    dependencies=[_can_view],
    name="list_staff",
)
def list_staff(
    db: DbSession,
    managers_only: Annotated[bool, Query()] = False,
) -> Any:
    """Staff available for assignment."""
    return client_service.list_staff(db, managers_only=managers_only)


@router.get(
    "/clients/{client_id}/audit",
    response_model=list[AuditEntryOut],
    dependencies=[_can_view],
    name="client_audit",
)
def client_audit(client_id: uuid.UUID, db: DbSession, scope: CallerClientScope) -> Any:
    """What has happened to this account, and who did it."""
    _load(db, scope, client_id)

    rows = db.execute(
        select(AuditLog, User.email)
        .outerjoin(User, User.id == AuditLog.actor_id)
        .where(AuditLog.entity_type == "client", AuditLog.entity_id == client_id)
        .order_by(AuditLog.created_at.desc())
    ).all()

    return [
        AuditEntryOut.model_validate(entry).model_copy(update={"actor_email": email})
        for entry, email in rows
    ]
