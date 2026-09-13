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
from app.models.client import Client, client_services
from app.models.enums import ClientStatus, UserRole
from app.models.service import ServiceCategory
from app.models.user import User
from app.schemas.client import (
    AuditEntryOut,
    ClientDetail,
    ClientFiltersOut,
    ClientServiceOut,
    ClientSummary,
    ClientUpdate,
    ManagerAssignmentRequest,
    ManagerClientsRequest,
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
        # Sorted here rather than relying on the relationship's order_by: after a
        # write, the collection in the session is in the order it was assigned,
        # and whether it reloads depends on the session's expire-on-commit
        # setting. Ordering the response explicitly makes it the same list every
        # time, whoever is asking and whatever just happened.
        "services": [
            ClientServiceOut.model_validate(category)
            for category in sorted(client.services, key=lambda c: (c.sort_order, c.name))
        ],
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
    service_id: Annotated[uuid.UUID | None, Query()] = None,
    country: Annotated[str | None, Query(max_length=128)] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> Any:
    stmt = (
        select(Client, User)
        .join(User, User.id == Client.user_id)
        # The ID breaks ties. Accounts created in the same transaction share a
        # created_at — `now()` is transaction-scoped — and without a tiebreaker
        # Postgres is free to return them in a different order each time, so the
        # list would reshuffle under the cursor after every edit.
        .order_by(Client.created_at.desc(), Client.id)
    )
    stmt = scope.apply(stmt, Client.id)

    if status_filter is not None:
        stmt = stmt.where(Client.status == status_filter)
    if unassigned:
        stmt = stmt.where(Client.assigned_manager_id.is_(None))
    elif manager_id is not None:
        stmt = stmt.where(Client.assigned_manager_id == manager_id)
    if service_id is not None:
        # A subquery, not a join. Joining the link table would return one row
        # per matching service, so a client taking several would appear several
        # times in the list — and the whole point of the services column is that
        # each client is listed once with all of theirs on that row.
        stmt = stmt.where(
            Client.id.in_(
                select(client_services.c.client_id).where(
                    client_services.c.category_id == service_id
                )
            )
        )
    if country:
        stmt = stmt.where(Client.country == country)
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
    "/client-filters",
    response_model=ClientFiltersOut,
    dependencies=[_can_view],
    name="filters",
)
def client_filters(db: DbSession, scope: CallerClientScope) -> Any:
    """What the client list can usefully be filtered by.

    Scoped like the list itself, so a Manager restricted to their own accounts
    is not shown the set of countries SmartAWARE's other clients are in.

    Not on a path under `/clients/` — that would sit alongside `/clients/{id}`
    and rely on route declaration order to avoid being parsed as a client ID.
    """
    countries = (
        db.execute(
            scope.apply(
                select(Client.country).where(Client.country.is_not(None)).distinct(),
                Client.id,
            )
        )
        .scalars()
        .all()
    )

    services = db.execute(
        select(ServiceCategory)
        .where(
            or_(
                ServiceCategory.is_archived.is_(False),
                # An archived service still filters, as long as somebody is
                # filed under it — otherwise those clients become unreachable
                # by the only filter that describes them.
                ServiceCategory.id.in_(select(client_services.c.category_id)),
            )
        )
        .order_by(ServiceCategory.sort_order, ServiceCategory.name)
    ).scalars()

    return ClientFiltersOut(
        countries=sorted(countries),
        services=[ClientServiceOut.model_validate(s) for s in services],
    )


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
    fields = payload.model_dump(exclude_unset=True)

    # Services are a relationship, not a column, and the IDs are caller-supplied
    # — so they are resolved and checked rather than assigned.
    if "service_ids" in fields:
        client.services = _resolve_services(db, fields.pop("service_ids"))

    for field, value in fields.items():
        setattr(client, field, value)
    db.commit()
    return get_client(client_id, db, scope)


def _resolve_services(db: Session, service_ids: list[uuid.UUID]) -> list[ServiceCategory]:
    """Turn caller-supplied IDs into categories, rejecting anything unknown.

    Duplicates are collapsed rather than refused — the same service twice is a
    request for that service, and the join table could not store it anyway.

    An archived category is accepted: a client can perfectly well still be
    engaged for something SmartAWARE has withdrawn from sale, and refusing it
    would make an existing client's services uneditable.
    """
    wanted = list(dict.fromkeys(service_ids))
    if not wanted:
        return []

    found = {
        category.id: category
        for category in db.execute(
            select(ServiceCategory).where(ServiceCategory.id.in_(wanted))
        ).scalars()
    }
    missing = [str(i) for i in wanted if i not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown service: {', '.join(missing)}.",
        )
    return [found[i] for i in wanted]


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


def _manager_or_404(db: Session, user_id: uuid.UUID) -> User:
    manager = db.get(User, user_id)
    if manager is None or manager.role is not UserRole.MANAGER:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found.")
    return manager


@router.get(
    "/staff/{user_id}/clients",
    response_model=list[ClientSummary],
    dependencies=[_can_view],
    name="manager_clients",
)
def manager_clients(user_id: uuid.UUID, db: DbSession, scope: CallerClientScope) -> Any:
    """The accounts this manager is looking after.

    Scoped like every other listing, so a Manager permitted to see this cannot
    learn about accounts outside their own reach by asking about a colleague.
    """
    _manager_or_404(db, user_id)
    stmt = (
        select(Client, User)
        .join(User, User.id == Client.user_id)
        .where(Client.assigned_manager_id == user_id)
        .order_by(Client.created_at.desc(), Client.id)
    )
    stmt = scope.apply(stmt, Client.id)
    rows = db.execute(stmt).all()
    manager = db.get(User, user_id)
    return [_summary(client, user, manager) for client, user in rows]


@router.put(
    "/staff/{user_id}/clients",
    response_model=list[ClientSummary],
    name="set_manager_clients",
)
def set_manager_clients(
    user_id: uuid.UUID,
    payload: ManagerClientsRequest,
    request: Request,
    admin: RequireAdmin,
    db: DbSession,
    scope: CallerClientScope,
) -> Any:
    """Tag a manager to a set of clients in one go.

    Admin only — Section 6.1 gives Managers no say in their own allocation.

    The same assignment the client page performs, applied per client, so each
    move is audited individually and a client taken from another manager records
    who lost it. Only the differences are written: re-sending an unchanged set
    is a no-op rather than a page of identical audit entries.
    """
    manager = _manager_or_404(db, user_id)
    if not manager.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That manager's account is not active.",
        )

    wanted = set(payload.client_ids)
    found = {
        client.id: client
        for client in db.execute(select(Client).where(Client.id.in_(wanted))).scalars()
    }
    missing = [str(i) for i in wanted if i not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown client: {', '.join(missing)}.",
        )

    current = {
        client.id: client
        for client in db.execute(
            select(Client).where(Client.assigned_manager_id == user_id)
        ).scalars()
    }

    changes = [(found[i], user_id) for i in wanted - current.keys()]
    changes += [(client, None) for i, client in current.items() if i not in wanted]

    ip = client_ip(request)
    for client, target in changes:
        try:
            client_service.assign_manager(
                db,
                client=client,
                manager_id=target,
                actor=admin,
                note=payload.note,
                ip_address=ip,
            )
        except client_service.ClientError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    db.commit()
    return manager_clients(user_id, db, scope)


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
