"""Archiving a service must not damage the history of completed work.

Admin needs to be able to remove a service from the website. But services are
referenced by tasks, so destroying the row would either break the foreign key
or orphan finished work. "Delete" therefore archives.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import generate_client_ref, hash_password
from app.models.client import Client
from app.models.enums import UserRole
from app.models.service import ServiceCategory
from app.models.task import Task
from app.models.user import User


def _make_client(db: Session) -> Client:
    user = User(
        email="archive-test@example.com",
        hashed_password=hash_password("x"),
        role=UserRole.CLIENT,
    )
    db.add(user)
    db.flush()
    client = Client(user_id=user.id, client_ref=generate_client_ref(), company_name="Acme Ltd")
    db.add(client)
    db.flush()
    return client


def test_archived_service_keeps_task_history(seeded_db: Session) -> None:
    client = _make_client(seeded_db)
    category = seeded_db.execute(
        select(ServiceCategory).where(ServiceCategory.slug == "bookkeeping")
    ).scalar_one()

    task = Task(
        client_id=client.id,
        title="FY24 bookkeeping",
        service_category_id=category.id,
    )
    seeded_db.add(task)
    seeded_db.flush()

    # Admin "deletes" the service from the portal.
    category.is_archived = True
    seeded_db.flush()

    reloaded = seeded_db.execute(select(Task).where(Task.id == task.id)).scalar_one()
    assert reloaded.service_category_id == category.id, "completed work must retain its category"


def test_archived_service_is_excluded_from_public_listing(seeded_db: Session) -> None:
    category = seeded_db.execute(
        select(ServiceCategory).where(ServiceCategory.slug == "bookkeeping")
    ).scalar_one()
    category.is_archived = True
    seeded_db.flush()

    live = (
        seeded_db.execute(
            select(ServiceCategory.slug).where(
                ServiceCategory.is_archived.is_(False),
                ServiceCategory.is_published.is_(True),
            )
        )
        .scalars()
        .all()
    )

    assert "bookkeeping" not in live
    assert len(live) == 11


def test_new_service_can_be_added_without_code(seeded_db: Session) -> None:
    """The requirement is that services are addable from the Admin Portal."""
    seeded_db.add(
        ServiceCategory(
            slug="company-secretarial",
            name="Company Secretarial",
            short_description="Added by an administrator at runtime.",
            sort_order=13,
        )
    )
    seeded_db.flush()

    found = seeded_db.execute(
        select(ServiceCategory).where(ServiceCategory.slug == "company-secretarial")
    ).scalar_one()
    assert found.is_published is True
    assert found.is_archived is False
