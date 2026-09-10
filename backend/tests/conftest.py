"""Shared pytest fixtures.

The test database is a real PostgreSQL (behaviour differs from SQLite for FTS,
citext, arrays, generated columns), so tests need `DATABASE_URL` pointing at a
throwaway database. `make test` runs inside the compose network where that is
already set.

Design:
    * schema is created once per session from `Base.metadata` (fast; the real
      migrations are exercised separately),
    * every test runs inside a transaction that is rolled back afterwards, so
      tests are isolated and order-independent.
"""

from __future__ import annotations

import os

import pytest

# Ensure a sane environment before anything imports app.config.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET", "test-secret-not-used-anywhere-real")
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get("DATABASE_URL", "postgresql+psycopg://jobhub:jobhub@db:5432/jobhub"),
)


@pytest.fixture(scope="session")
def _schema():
    """Create all tables once for the test session, drop them at the end."""
    import app.models  # noqa: F401  — registers every model on Base.metadata
    from app.db.base import Base
    from app.db.session import engine

    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db(_schema):
    """A transactional session, rolled back after each test."""
    from app.db.session import SessionLocal, engine

    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db):
    """FastAPI TestClient with the DB dependency bound to the test session."""
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
