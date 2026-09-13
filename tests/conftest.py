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
