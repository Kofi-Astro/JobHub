"""Job-seeker account endpoints: saved jobs, saved searches (+ alerts), and
the anonymous-state merge on first login.

Every route here requires a logged-in seeker — browsing/search/apply never do
(see routes/jobs.py). `require_role(UserRole.SEEKER)` is intentionally strict:
an employer or admin token does not unlock a seeker's saved-jobs list, even
though nothing stops the same email from holding one of each role in theory
(it can't in practice — one email is one `User` row with one role).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db import get_db
from app.models import Job, SavedJob, SavedSearch, User
from app.models.enums import AnalyticsEventType, UserRole
from app.schemas.common import Message
from app.schemas.jobs import JobCard
from app.schemas.seeker import (
    MergeAnonIn,
    MergeAnonOut,
    SavedJobOut,
    SavedSearchIn,
    SavedSearchOut,
    SavedSearchUpdateIn,
    SaveJobIn,
)
from app.services.analytics import record_event

router = APIRouter(prefix="/api/seeker", tags=["seeker"])

_seeker = require_role(UserRole.SEEKER)


# ---------------------------------------------------------------------------
# Saved jobs
# ---------------------------------------------------------------------------


@router.get("/saved-jobs", response_model=list[SavedJobOut])
def list_saved_jobs(
    user: User = Depends(_seeker), db: Session = Depends(get_db)
) -> list[SavedJobOut]:
    rows = db.scalars(
        select(SavedJob).where(SavedJob.user_id == user.id).order_by(SavedJob.created_at.desc())
    ).all()
    return [
        SavedJobOut(id=r.id, notes=r.notes, created_at=r.created_at, job=JobCard.from_job(r.job))
        for r in rows
        if r.job is not None
    ]


@router.post("/saved-jobs", response_model=SavedJobOut, status_code=201)
def save_job(
    body: SaveJobIn, user: User = Depends(_seeker), db: Session = Depends(get_db)
) -> SavedJobOut:
    job = db.get(Job, body.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    existing = db.scalar(
        select(SavedJob).where(SavedJob.user_id == user.id, SavedJob.job_id == job.id)
    )
    if existing is not None:
        return SavedJobOut(
            id=existing.id,
            notes=existing.notes,
            created_at=existing.created_at,
            job=JobCard.from_job(job),
        )

    row = SavedJob(user_id=user.id, job_id=job.id, notes=body.notes)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race with a duplicate save from another tab — fine, treat as success.
        db.rollback()
        row = db.scalar(
            select(SavedJob).where(SavedJob.user_id == user.id, SavedJob.job_id == job.id)
        )
        if row is None:  # pragma: no cover - would mean the race resolved by deletion
            raise HTTPException(status_code=409, detail="Could not save this job.") from None

    record_event(db, AnalyticsEventType.SAVED_JOB, user_id=user.id, job_id=job.id)
    return SavedJobOut(
        id=row.id, notes=row.notes, created_at=row.created_at, job=JobCard.from_job(job)
    )


@router.delete("/saved-jobs/{job_id}", response_model=Message)
def unsave_job(
    job_id: uuid.UUID, user: User = Depends(_seeker), db: Session = Depends(get_db)
) -> Message:
    row = db.scalar(select(SavedJob).where(SavedJob.user_id == user.id, SavedJob.job_id == job_id))
    if row is not None:
        db.delete(row)
        db.commit()
    return Message(detail="Removed.")


# ---------------------------------------------------------------------------
# Saved searches (+ alerts)
# ---------------------------------------------------------------------------


@router.get("/saved-searches", response_model=list[SavedSearchOut])
def list_saved_searches(
    user: User = Depends(_seeker), db: Session = Depends(get_db)
) -> list[SavedSearchOut]:
    rows = db.scalars(
        select(SavedSearch)
        .where(SavedSearch.user_id == user.id)
        .order_by(SavedSearch.created_at.desc())
    ).all()
    return [SavedSearchOut.model_validate(r) for r in rows]


@router.post("/saved-searches", response_model=SavedSearchOut, status_code=201)
def create_saved_search(
    body: SavedSearchIn, user: User = Depends(_seeker), db: Session = Depends(get_db)
) -> SavedSearchOut:
    if body.alert_enabled and body.alert_frequency is None:
        raise HTTPException(
            status_code=422, detail="alert_frequency is required when alert_enabled is true."
        )
    row = SavedSearch(
        user_id=user.id,
        name=body.name,
        query_params=body.query_params,
        alert_enabled=body.alert_enabled,
        alert_frequency=body.alert_frequency,
    )
    db.add(row)
    db.commit()
    record_event(
        db, AnalyticsEventType.SAVED_SEARCH, user_id=user.id, properties={"name": row.name}
    )
    return SavedSearchOut.model_validate(row)


@router.patch("/saved-searches/{search_id}", response_model=SavedSearchOut)
def update_saved_search(
    search_id: uuid.UUID,
    body: SavedSearchUpdateIn,
    user: User = Depends(_seeker),
    db: Session = Depends(get_db),
) -> SavedSearchOut:
    row = db.scalar(
        select(SavedSearch).where(SavedSearch.id == search_id, SavedSearch.user_id == user.id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Saved search not found.")

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(row, field, value)

    if row.alert_enabled and row.alert_frequency is None:
        raise HTTPException(
            status_code=422, detail="alert_frequency is required when alert_enabled is true."
        )
    db.commit()
    return SavedSearchOut.model_validate(row)


@router.delete("/saved-searches/{search_id}", response_model=Message)
def delete_saved_search(
    search_id: uuid.UUID, user: User = Depends(_seeker), db: Session = Depends(get_db)
) -> Message:
    row = db.scalar(
        select(SavedSearch).where(SavedSearch.id == search_id, SavedSearch.user_id == user.id)
    )
    if row is not None:
        db.delete(row)
        db.commit()
    return Message(detail="Deleted.")


# ---------------------------------------------------------------------------
# Anonymous-state merge (called once, right after the first successful login)
# ---------------------------------------------------------------------------


@router.post("/merge-anon", response_model=MergeAnonOut)
def merge_anon(
    body: MergeAnonIn, user: User = Depends(_seeker), db: Session = Depends(get_db)
) -> MergeAnonOut:
    if not body.saved_job_ids:
        return MergeAnonOut(saved_jobs_merged=0)

    existing_job_ids = set(db.scalars(select(SavedJob.job_id).where(SavedJob.user_id == user.id)))
    valid_job_ids = set(db.scalars(select(Job.id).where(Job.id.in_(body.saved_job_ids))))
    to_add = valid_job_ids - existing_job_ids

    for job_id in to_add:
        db.add(SavedJob(user_id=user.id, job_id=job_id))
    db.commit()
    return MergeAnonOut(saved_jobs_merged=len(to_add))
