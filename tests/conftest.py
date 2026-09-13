"""Test fixtures.

Tests run against a real Postgres database created from the Alembic migrations,
not from `create_all`. That means every test run also proves the migrations
produce the schema the models expect — the two cannot silently diverge.

Each test runs inside a transaction that is rolled back afterwards, so tests
are isolated and the database does not need rebuilding between them.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from urllib.parse import urlparse, urlunparse

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

TEST_DB_NAME = "smartaware_test"


def _test_database_url() -> str:
    from app.core.config import settings

    parts = urlparse(settings.DATABASE_URL)
    return urlunparse(parts._replace(path=f"/{TEST_DB_NAME}"))


@pytest.fixture(scope="session", autouse=True)
def _configure_test_env() -> None:
    os.environ["ENVIRONMENT"] = "test"


@pytest.fixture(scope="session")
def engine(_configure_test_env: None) -> Generator[sa.Engine, None, None]:
    from app.core.config import settings

    admin_url = urlunparse(urlparse(settings.DATABASE_URL)._replace(path="/postgres"))
    admin_engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(
            sa.text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB_NAME}
        ).scalar()
        if not exists:
            conn.execute(sa.text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin_engine.dispose()

    url = _test_database_url()

    # Point Alembic at the test database and build the schema from migrations.
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    test_engine = sa.create_engine(url)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def db(engine: sa.Engine) -> Generator[Session, None, None]:
    """A session wrapped in a transaction that is always rolled back."""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def seeded_db(db: Session) -> Session:
    from app.seeds.run import seed_all

    seed_all(db)
    return db


@pytest.fixture
def client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app())


# --- Auth fixtures -----------------------------------------------------------


@pytest.fixture
def api(db: Session) -> Generator[TestClient, None, None]:
    """A TestClient whose requests share the test transaction.

    Overriding get_db means requests see the fixtures a test created without
    committing them, and everything rolls back afterwards.
    """
    from app.db.session import get_db
    from app.main import create_app
    from app.seeds.run import seed_all

    seed_all(db)

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(db: Session):
    """Factory for users, optionally with an attached client profile."""
    from app.core.security import generate_client_ref, hash_password
    from app.models.client import Client
    from app.models.enums import ClientStatus, UserRole
    from app.models.user import User

    counter = {"n": 0}

    def _make(
        role: UserRole = UserRole.CLIENT,
        *,
        email: str | None = None,
        password: str = "correct horse battery staple",
        is_active: bool = True,
        client_status: ClientStatus = ClientStatus.ACTIVE,
        assigned_manager=None,
        company_name: str | None = None,
    ):
        counter["n"] += 1
        user = User(
            email=email or f"{role.value}{counter['n']}@example.com",
            hashed_password=hash_password(password),
            role=role,
            is_active=is_active,
            full_name=f"Test {role.value.title()} {counter['n']}",
        )
        db.add(user)
        db.flush()

        client = None
        if role is UserRole.CLIENT:
            client = Client(
                user_id=user.id,
                client_ref=generate_client_ref(),
                company_name=company_name or f"Client Co {counter['n']}",
                status=client_status,
                assigned_manager_id=assigned_manager.id if assigned_manager else None,
            )
            db.add(client)
            db.flush()

        return user, client

    return _make


@pytest.fixture
def login(api: TestClient):
    """Sign in and return an Authorization header."""

    def _login(email: str, password: str = "correct horse battery staple") -> dict[str, str]:
        response = api.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _login
