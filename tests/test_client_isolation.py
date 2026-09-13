"""Client data isolation — spec Section 9.

"Client data isolation must be enforced via query-level scoping, not just UI
filtering." These tests exercise `resolve_client_scope` directly, because it is
the single choke point every client-owned query passes through.

As each client-facing resource is built (tasks, documents, invoices, notes), a
cross-tenant case for it belongs in this file.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import resolve_client_scope
from app.core.settings_service import SettingKey, invalidate, set_setting
from app.models.client import Client
from app.models.enums import ClientStatus, UserRole
from app.models.task import Task


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    invalidate()


# --- Clients ------------------------------------------------------------------


def test_client_scope_contains_only_their_own_record(seeded_db: Session, make_user) -> None:
    user_a, client_a = make_user(UserRole.CLIENT)
    _, client_b = make_user(UserRole.CLIENT)

    scope = resolve_client_scope(seeded_db, user_a)

    assert scope.all_clients is False
    assert scope.client_ids == frozenset({client_a.id})
    assert scope.allows(client_a.id) is True
    assert scope.allows(client_b.id) is False


def test_client_cannot_reach_another_clients_tasks(seeded_db: Session, make_user) -> None:
    user_a, client_a = make_user(UserRole.CLIENT)
    _, client_b = make_user(UserRole.CLIENT)

    seeded_db.add_all(
        [
            Task(client_id=client_a.id, title="Client A return"),
            Task(client_id=client_b.id, title="Client B return"),
        ]
    )
    seeded_db.flush()

    scope = resolve_client_scope(seeded_db, user_a)
    titles = seeded_db.execute(scope.apply(select(Task.title), Task.client_id)).scalars().all()

    assert titles == ["Client A return"]


def test_scoping_survives_a_guessed_identifier(seeded_db: Session, make_user) -> None:
    """Even asking for a specific foreign ID must return nothing."""
    user_a, _ = make_user(UserRole.CLIENT)
    _, client_b = make_user(UserRole.CLIENT)

    seeded_db.add(Task(client_id=client_b.id, title="Client B return"))
    seeded_db.flush()

    scope = resolve_client_scope(seeded_db, user_a)
    stmt = scope.apply(select(Task).where(Task.client_id == client_b.id), Task.client_id)
    assert seeded_db.execute(stmt).scalars().all() == []


def test_unknown_client_id_is_not_allowed(seeded_db: Session, make_user) -> None:
    user, _ = make_user(UserRole.CLIENT)
    scope = resolve_client_scope(seeded_db, user)
    assert scope.allows(uuid.uuid4()) is False
    assert scope.allows(None) is False


# --- Managers (Section 13 item 5) --------------------------------------------


def test_manager_sees_only_assigned_clients_by_default(seeded_db: Session, make_user) -> None:
    manager, _ = make_user(UserRole.MANAGER)
    other_manager, _ = make_user(UserRole.MANAGER)

    _, mine = make_user(UserRole.CLIENT, assigned_manager=manager)
    _, theirs = make_user(UserRole.CLIENT, assigned_manager=other_manager)
    _, unassigned = make_user(UserRole.CLIENT)

    scope = resolve_client_scope(seeded_db, manager)

    assert scope.all_clients is False
    assert scope.allows(mine.id) is True
    assert scope.allows(theirs.id) is False
    assert scope.allows(unassigned.id) is False


def test_manager_scope_widens_when_the_setting_says_all(seeded_db: Session, make_user) -> None:
    manager, _ = make_user(UserRole.MANAGER)
    other_manager, _ = make_user(UserRole.MANAGER)
    _, theirs = make_user(UserRole.CLIENT, assigned_manager=other_manager)

    assert resolve_client_scope(seeded_db, manager).allows(theirs.id) is False

    set_setting(seeded_db, SettingKey.MANAGER_CLIENT_SCOPE, "all")

    assert resolve_client_scope(seeded_db, manager).all_clients is True


def test_reassigning_a_manager_moves_access_immediately(seeded_db: Session, make_user) -> None:
    manager_a, _ = make_user(UserRole.MANAGER)
    manager_b, _ = make_user(UserRole.MANAGER)
    _, client = make_user(UserRole.CLIENT, assigned_manager=manager_a)

    assert resolve_client_scope(seeded_db, manager_a).allows(client.id) is True
    assert resolve_client_scope(seeded_db, manager_b).allows(client.id) is False

    client.assigned_manager_id = manager_b.id
    seeded_db.flush()

    assert resolve_client_scope(seeded_db, manager_a).allows(client.id) is False
    assert resolve_client_scope(seeded_db, manager_b).allows(client.id) is True


# --- Admin --------------------------------------------------------------------


def test_admin_scope_covers_every_client(seeded_db: Session, make_user) -> None:
    admin, _ = make_user(UserRole.ADMIN)
    _, client_a = make_user(UserRole.CLIENT)
    _, client_b = make_user(UserRole.CLIENT)

    scope = resolve_client_scope(seeded_db, admin)

    assert scope.all_clients is True
    assert scope.allows(client_a.id) and scope.allows(client_b.id)
    assert seeded_db.execute(scope.apply(select(Client.id), Client.id)).scalars().all() != []


# --- Failing closed -----------------------------------------------------------


def test_inactive_user_has_an_empty_scope(seeded_db: Session, make_user) -> None:
    admin, _ = make_user(UserRole.ADMIN, is_active=False)
    scope = resolve_client_scope(seeded_db, admin)
    assert scope.is_empty is True
    assert scope.all_clients is False


def test_empty_scope_matches_no_rows_rather_than_all(seeded_db: Session, make_user) -> None:
    """The failure mode that matters: an empty scope must not degrade into an
    unfiltered query returning every client's data."""
    manager, _ = make_user(UserRole.MANAGER)  # no assigned clients
    _, other = make_user(UserRole.CLIENT)
    seeded_db.add(Task(client_id=other.id, title="Someone else's task"))
    seeded_db.flush()

    scope = resolve_client_scope(seeded_db, manager)
    assert scope.is_empty is True

    rows = seeded_db.execute(scope.apply(select(Task), Task.client_id)).scalars().all()
    assert rows == []


def test_client_on_hold_keeps_a_scope_but_cannot_authenticate(
    seeded_db: Session, make_user
) -> None:
    """Scope and login are separate gates: Hold blocks the session, it does not
    quietly widen or empty the data scope."""
    user, client = make_user(UserRole.CLIENT, client_status=ClientStatus.HOLD)
    scope = resolve_client_scope(seeded_db, user)
    assert scope.allows(client.id) is True
