"""Deleting a user must remove their client profile, matching the FK."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.enums import UserRole


def test_deleting_a_user_cascades_to_their_client(db: Session, make_user) -> None:
    user, client = make_user(UserRole.CLIENT)
    assert db.execute(select(func.count()).select_from(Client)).scalar_one() == 1

    db.delete(user)
    db.flush()

    assert db.execute(select(func.count()).select_from(Client)).scalar_one() == 0
