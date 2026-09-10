"""Meta / operational endpoints: health and version.

These have no auth and no side effects. `/api/health` is what the Docker
HEALTHCHECK and the Railway healthcheck hit, so it must stay cheap and only fail
when the process genuinely cannot serve traffic.

Later milestones add data-backed meta endpoints here:
    GET /api/meta/countries  — distinct countries present in active jobs
    GET /api/meta/sources    — public source list for the "Source" filter
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.config import get_settings
from app.db import get_db

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health", summary="Liveness + readiness probe")
def health(db: Session = Depends(get_db)) -> dict:
    """Return 200 when the process is up AND the database is reachable.

    WHY check the DB: a container that cannot reach Postgres is not "healthy" for
    our purposes — Railway should restart it / hold traffic rather than route
    users to an instance that will 500 on every real request. The query is
    `SELECT 1`, cheap enough to run on every probe.
    """
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "version": __version__,
        "environment": get_settings().environment,
    }


@router.get("/version", summary="Deployed application version")
def version() -> dict:
    return {"version": __version__}
