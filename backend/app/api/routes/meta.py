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
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import __version__
from app.config import get_settings
from app.db import get_db
from app.models import Job, Source
from app.models.enums import JobOrigin, JobStatus

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


class CountryOut(BaseModel):
    code: str
    name: str
    job_count: int


class SourceOut(BaseModel):
    key: str
    name: str
    job_count: int


@router.get(
    "/meta/countries",
    response_model=list[CountryOut],
    summary="Countries with active jobs (for the location filter)",
)
def countries(db: Session = Depends(get_db)) -> list[CountryOut]:
    """Only countries that actually have visible jobs — so the filter never
    offers a dead option."""
    rows = db.execute(
        select(Job.country_code, Job.country_name, func.count())
        .where(
            Job.status == JobStatus.ACTIVE,
            Job.is_canonical.is_(True),
            Job.country_code.isnot(None),
        )
        .group_by(Job.country_code, Job.country_name)
        .order_by(func.count().desc())
    ).all()
    # Collapse any (code, differing name) rows to the first name seen.
    seen: dict[str, CountryOut] = {}
    for code, name, count in rows:
        if code in seen:
            seen[code].job_count += count
        else:
            seen[code] = CountryOut(code=code, name=name or code, job_count=count)
    return list(seen.values())


@router.get(
    "/meta/sources",
    response_model=list[SourceOut],
    summary="Public source list for the Source filter",
)
def sources(db: Session = Depends(get_db)) -> list[SourceOut]:
    counts = dict(
        db.execute(
            select(Job.source_id, func.count())
            .where(Job.status == JobStatus.ACTIVE, Job.is_canonical.is_(True))
            .group_by(Job.source_id)
        ).all()
    )
    out = [
        SourceOut(key=s.key, name=s.name, job_count=counts.get(s.id, 0))
        for s in db.scalars(select(Source).order_by(Source.name))
        if counts.get(s.id, 0) > 0
    ]
    employer_jobs = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(
            Job.origin == JobOrigin.EMPLOYER,
            Job.status == JobStatus.ACTIVE,
            Job.is_canonical.is_(True),
        )
    )
    if employer_jobs:
        out.append(SourceOut(key="employer", name="Direct from employer", job_count=employer_jobs))
    return out
