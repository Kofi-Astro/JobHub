"""Shared pytest fixtures.

The test database is a real PostgreSQL — behaviour differs from SQLite for the
things this schema leans on (full-text search, `citext`, arrays, generated
columns, partial indexes). Point `DATABASE_URL` at a throwaway database;
`make test` does this inside the compose network.

Isolation model:
    * `_migrated` (session): brings the schema to `head` via the real Alembic
      migrations — so tests also prove the migrations run.
    * `db` (function): runs each test inside a SAVEPOINT-backed transaction that
      is rolled back afterwards, so tests never see each other's writes and
      order does not matter.
    * `seeded` (function): loads the taxonomy + source registry *inside* that
      transaction, for tests that need real categories/sources.
"""

from __future__ import annotations

import os

import pytest

# A sane environment must exist before anything imports app.config.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET", "test-secret-not-used-anywhere-real")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://jobhub:jobhub@db:5432/jobhub",
)


@pytest.fixture(scope="session")
def _migrated():
    """Upgrade the test database to the latest migration once per session."""
    from alembic.config import Config

    from alembic import command

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture
def db(_migrated):
    """A transactional session, rolled back after each test.

    Uses the "join an external transaction" pattern: a real transaction is
    opened on a dedicated connection, the session runs inside it, and everything
    is rolled back at teardown — including anything the code under test
    committed (those become nested SAVEPOINT releases, not real commits).
    """
    from sqlalchemy import event, text

    from app.db.base import Base
    from app.db.session import SessionLocal, engine

    connection = engine.connect()
    trans = connection.begin()

    # Start every test from an empty database. This TRUNCATE is inside the
    # outer transaction that gets rolled back at teardown, so a developer's
    # local data in the same database is untouched after the run — but tests
    # never see it (or each other's writes).
    tables = ", ".join(f'"{t}"' for t in Base.metadata.tables)
    connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))

    session = SessionLocal(bind=connection, join_transaction_mode="create_savepoint")

    # Re-open a SAVEPOINT each time the code under test calls commit().
    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, transaction):  # pragma: no cover - plumbing
        if transaction.nested and not transaction._parent.nested:
            sess.begin_nested()

    session.begin_nested()
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()


@pytest.fixture
def seeded(db):
    """Load taxonomy + sources into the current test transaction."""
    from app.seeds.run import seed_sources, seed_taxonomy

    seed_taxonomy(db)
    seed_sources(db)
    db.flush()
    return db


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
