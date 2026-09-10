"""Engine and session management.

WHAT: One synchronous SQLAlchemy engine per process, plus two ways to get a
session:
    * `get_db()`      — FastAPI dependency (request-scoped, auto-close)
    * `session_scope()` — context manager for scripts / worker tasks

WHY synchronous (not async) SQLAlchemy: the workload is short OLTP queries and
batch ingestion, not thousands of concurrent slow connections. Sync code is
simpler to write correctly and to reason about, and FastAPI runs sync
dependencies in a threadpool so the event loop is not blocked. The `JobQuery`
seam in `services/search.py` keeps the door open to swap the read path later.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_settings = get_settings()

# pool_pre_ping: transparently recycle connections dropped by the DB / a
#   proxy (Railway closes idle connections) instead of failing the next query.
# pool_size / max_overflow: conservative — the API has few workers and the
#   worker process runs tasks serially.
engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    future=True,
    # Echo SQL only when explicitly debugging locally.
    echo=False,
)

# expire_on_commit=False: returned ORM objects stay usable after the session
# commits, which is what route handlers and serializers expect.
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a session, always closes it.

    Transaction policy: route handlers call `db.commit()` explicitly when they
    mutate. On an unhandled exception the session is closed without commit, so
    partial writes roll back.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for non-request code (seeds, ingestion, worker tasks).

    Commits on clean exit, rolls back on exception, always closes. This is the
    right default for batch work that should be atomic per unit.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
