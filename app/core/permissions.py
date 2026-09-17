"""The authorisation matrix — spec Section 6.1.

This module is the single source of truth for who may do what. Route handlers
ask questions here; they never re-derive a rule inline. Spec Section 9 is
explicit that role checks live at the API layer and that hiding a button is not
a security control, so the frontend's role-aware UI is a convenience and this
file is the boundary.

Two rules are deliberately expressed as data rather than code because
SmartAWARE has not confirmed them (Section 13 items 5 and 6): whether a Manager
sees all clients or only assigned ones, and whether a Manager may edit content.
Both are read from the `settings` table at call time.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass

from sqlalchemy import Select
from sqlalchemy.orm import Session

from app.core.settings_service import SettingKey, get_setting
from app.models.client import Client
from app.models.enums import UserRole
from app.models.user import User


class Permission(enum.StrEnum):
    # Tasks (Section 6.1 / 6.3)
    TASK_VIEW = "task:view"
    TASK_CREATE = "task:create"
    TASK_UPDATE = "task:update"
    TASK_COMPLETE = "task:complete"
    TASK_ASSIGN = "task:assign"
    TASK_DELETE = "task:delete"

    # Clients
    CLIENT_VIEW = "client:view"
    CLIENT_CREATE = "client:create"
    CLIENT_UPDATE = "client:update"
    CLIENT_SET_STATUS = "client:set_status"
    CLIENT_ASSIGN_MANAGER = "client:assign_manager"

    # Invites (Section 5.1 / 6.2)
    INVITE_MANAGE = "invite:manage"

    # Documents (Section 5.3.E / 5.3.F)
    DOCUMENT_VIEW = "document:view"
    DOCUMENT_UPLOAD = "document:upload"
    DOCUMENT_UPLOAD_AS_STAFF = "document:upload_as_staff"
    DOCUMENT_DELETE = "document:delete"

    # Invoices (Section 5.3.D / 12)
    INVOICE_VIEW = "invoice:view"
    INVOICE_MANAGE = "invoice:manage"
    INVOICE_RECONCILE = "invoice:reconcile"

    # Notes (Section 5.3.G)
    NOTE_VIEW = "note:view"
    NOTE_MANAGE = "note:manage"

    # Content and FAQ (Sections 3, 4.3)
    CONTENT_MANAGE = "content:manage"
    FAQ_MANAGE = "faq:manage"

    # Administration
    SETTINGS_MANAGE = "settings:manage"
    USER_MANAGE = "user:manage"
    ENQUIRY_VIEW = "enquiry:view"
    AUDIT_VIEW = "audit:view"


#: Static grants. Anything absent is denied — there is no implicit inheritance
#: between roles, so a new permission defaults to "nobody" until named here.
ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.ADMIN: frozenset(Permission),
    UserRole.MANAGER: frozenset(
        {
            Permission.TASK_VIEW,
            Permission.TASK_CREATE,
            Permission.TASK_UPDATE,
            Permission.TASK_COMPLETE,
            Permission.TASK_ASSIGN,
            # TASK_DELETE is deliberately absent. Section 6.1 restricts deletion to
            # Admin, and Section 6.2 requires that to be enforced at the API layer
            # so it cannot be bypassed by calling the endpoint directly.
            Permission.CLIENT_VIEW,
            Permission.CLIENT_UPDATE,
            Permission.DOCUMENT_VIEW,
            Permission.DOCUMENT_UPLOAD_AS_STAFF,
            Permission.INVOICE_VIEW,
            Permission.NOTE_VIEW,
            Permission.NOTE_MANAGE,
            Permission.ENQUIRY_VIEW,
        }
    ),
    UserRole.CLIENT: frozenset(
        {
            # View-only on tasks — Section 5.3.B gives clients no create, edit,
            # delete or complete rights.
            Permission.TASK_VIEW,
            Permission.DOCUMENT_VIEW,
            Permission.DOCUMENT_UPLOAD,
            Permission.INVOICE_VIEW,
            Permission.NOTE_VIEW,
        }
    ),
}

#: Permissions a Manager holds only when a setting says so.
_MANAGER_SETTING_GATED: dict[Permission, tuple[str, object]] = {
    Permission.CONTENT_MANAGE: (SettingKey.MANAGER_CAN_MANAGE_CONTENT, True),
    Permission.FAQ_MANAGE: (SettingKey.MANAGER_CAN_MANAGE_CONTENT, True),
}


def has_permission(db: Session, user: User, permission: Permission) -> bool:
    """Whether `user` holds `permission` right now."""
    if not user.is_active:
        return False

    if permission in ROLE_PERMISSIONS.get(user.role, frozenset()):
        return True

    if user.role is UserRole.MANAGER and permission in _MANAGER_SETTING_GATED:
        key, expected = _MANAGER_SETTING_GATED[permission]
        return get_setting(db, key, False) == expected

    return False


def effective_permissions(db: Session, user: User) -> frozenset[Permission]:
    """Everything `user` may do right now.

    Derived by asking `has_permission` for each one rather than reassembling the
    rules, so the answer cannot drift from what the endpoints actually enforce —
    including the two a setting turns on for Managers at runtime.

    The frontend uses this to decide what to put in its navigation. That is a
    convenience: a section it shows anyway is still refused by the API. The
    point is to avoid offering a Manager a page that will only reject them.
    """
    return frozenset(p for p in Permission if has_permission(db, user, p))


@dataclass(frozen=True)
class ClientScope:
    """Which clients a user may reach.

    Spec Section 9 requires client isolation to be enforced by scoping queries,
    not by filtering in the UI. Every query touching client-owned data runs
    through `apply()`, so a client can never read another client's records by
    calling the API directly with a guessed ID.
    """

    all_clients: bool
    client_ids: frozenset[uuid.UUID]

    @property
    def is_empty(self) -> bool:
        return not self.all_clients and not self.client_ids

    def allows(self, client_id: uuid.UUID | None) -> bool:
        if client_id is None:
            return False
        return self.all_clients or client_id in self.client_ids

    def apply(self, stmt: Select, client_id_column) -> Select:
        """Constrain a SELECT to the clients this user may see."""
        if self.all_clients:
            return stmt
        if not self.client_ids:
            # No accessible clients. Return a statement that matches nothing
            # rather than an unfiltered one — failing closed matters here.
            return stmt.where(client_id_column.in_([]))
        return stmt.where(client_id_column.in_(self.client_ids))


def resolve_client_scope(db: Session, user: User) -> ClientScope:
    """Compute the caller's client scope.

    Kept as one function so the rule lives in a single place. If SmartAWARE
    later allows one login to act for several businesses, only this function
    changes — not every query that uses it.
    """
    if not user.is_active:
        return ClientScope(all_clients=False, client_ids=frozenset())

    if user.role is UserRole.ADMIN:
        return ClientScope(all_clients=True, client_ids=frozenset())

    if user.role is UserRole.MANAGER:
        scope = get_setting(db, SettingKey.MANAGER_CLIENT_SCOPE, "assigned")
        if scope == "all":
            return ClientScope(all_clients=True, client_ids=frozenset())
        assigned = db.execute(
            Client.__table__.select()
            .with_only_columns(Client.id)
            .where(Client.assigned_manager_id == user.id)
        ).scalars()
        return ClientScope(all_clients=False, client_ids=frozenset(assigned))

    # A client reaches exactly their own record, and only while active.
    own = db.execute(
        Client.__table__.select().with_only_columns(Client.id).where(Client.user_id == user.id)
    ).scalars()
    return ClientScope(all_clients=False, client_ids=frozenset(own))
