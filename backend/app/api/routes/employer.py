"""Employer posting portal: create/edit/close/republish listings, view basic
stats. Every route requires an approved... no — requires a LOGGED-IN employer;
account approval gates whether a *posting* goes live, not whether the
dashboard itself is usable (an employer should be able to see "pending
approval" rather than being locked out of their own account).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db import get_db
from app.models import Job, User
from app.models.enums import AnalyticsEventType, JobOrigin, JobStatus, UserRole
from app.schemas.employer import (
    EmployerJobOut,
    EmployerStatsOut,
    JobPostIn,
    JobPostUpdateIn,
)
from app.schemas.jobs import location_label  # shared display-label logic
from app.services.analytics import record_event
from app.services.employer_jobs import (
    EmployerJobError,
    close_employer_job,
    create_employer_job,
    republish_employer_job,
    update_employer_job,
)

router = APIRouter(prefix="/api/employer", tags=["employer"])

_employer = require_role(UserRole.EMPLOYER)


def _profile(user: User):
    """Every `role=employer` User has an EmployerProfile (created together at
    registration) — this should never be None, but fail clearly if it is."""
    if user.employer_profile is None:  # pragma: no cover - data-integrity guard
        raise HTTPException(status_code=500, detail="Employer profile is missing.")
    return user.employer_profile


def _to_out(job: Job) -> EmployerJobOut:
    return EmployerJobOut(
        id=job.id,
        title=job.title,
        status=job.status,
        moderation_status=job.moderation_status,
        field_slug=job.field.slug if job.field else None,
        subfield_slug=job.subfield.slug if job.subfield else None,
        location_label=location_label(job),
        workplace_type=job.workplace_type,
        job_type=job.job_type,
        experience_level=job.experience_level,
        apply_url=job.apply_url,
        apply_email=job.apply_email,
        view_count=job.view_count,
        apply_click_count=job.apply_click_count,
        posted_at=job.posted_at,
        created_at=job.created_at,
    )


def _own_job_or_404(db: Session, user: User, job_id: uuid.UUID) -> Job:
    job = db.scalar(
        select(Job).where(
            Job.id == job_id, Job.origin == JobOrigin.EMPLOYER, Job.posted_by_user_id == user.id
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@router.post("/jobs", response_model=EmployerJobOut, status_code=201)
def post_job(
    body: JobPostIn, user: User = Depends(_employer), db: Session = Depends(get_db)
) -> EmployerJobOut:
    try:
        job = create_employer_job(db, _profile(user), body)
    except EmployerJobError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_event(db, AnalyticsEventType.JOB_POST, user_id=user.id, job_id=job.id)
    return _to_out(job)


@router.get("/jobs", response_model=list[EmployerJobOut])
def list_my_jobs(
    user: User = Depends(_employer), db: Session = Depends(get_db)
) -> list[EmployerJobOut]:
    rows = db.scalars(
        select(Job)
        .where(Job.origin == JobOrigin.EMPLOYER, Job.posted_by_user_id == user.id)
        .order_by(Job.created_at.desc())
    ).all()
    return [_to_out(j) for j in rows]


@router.get("/jobs/{job_id}", response_model=EmployerJobOut)
def get_my_job(
    job_id: uuid.UUID, user: User = Depends(_employer), db: Session = Depends(get_db)
) -> EmployerJobOut:
    return _to_out(_own_job_or_404(db, user, job_id))


@router.patch("/jobs/{job_id}", response_model=EmployerJobOut)
def edit_job(
    job_id: uuid.UUID,
    body: JobPostUpdateIn,
    user: User = Depends(_employer),
    db: Session = Depends(get_db),
) -> EmployerJobOut:
    job = _own_job_or_404(db, user, job_id)
    if job.status == JobStatus.CLOSED:
        raise HTTPException(
            status_code=409, detail="Reopen (republish) this listing before editing it."
        )
    try:
        job = update_employer_job(db, job, body)
    except EmployerJobError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_out(job)


@router.post("/jobs/{job_id}/close", response_model=EmployerJobOut)
def close_job(
    job_id: uuid.UUID, user: User = Depends(_employer), db: Session = Depends(get_db)
) -> EmployerJobOut:
    job = _own_job_or_404(db, user, job_id)
    return _to_out(close_employer_job(db, job))


@router.post("/jobs/{job_id}/republish", response_model=EmployerJobOut)
def republish_job(
    job_id: uuid.UUID, user: User = Depends(_employer), db: Session = Depends(get_db)
) -> EmployerJobOut:
    job = _own_job_or_404(db, user, job_id)
    if job.status != JobStatus.CLOSED:
        raise HTTPException(status_code=409, detail="Only a closed listing can be republished.")
    try:
        job = republish_employer_job(db, job)
    except EmployerJobError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_out(job)


@router.get("/stats", response_model=EmployerStatsOut)
def stats(user: User = Depends(_employer), db: Session = Depends(get_db)) -> EmployerStatsOut:
    base = select(Job).where(Job.origin == JobOrigin.EMPLOYER, Job.posted_by_user_id == user.id)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    active = db.scalar(
        select(func.count()).select_from(base.where(Job.status == JobStatus.ACTIVE).subquery())
    )
    pending = db.scalar(
        select(func.count()).select_from(base.where(Job.status == JobStatus.PENDING).subquery())
    )
    views, clicks = db.execute(
        select(
            func.coalesce(func.sum(Job.view_count), 0),
            func.coalesce(func.sum(Job.apply_click_count), 0),
        ).select_from(base.subquery())
    ).one()
    return EmployerStatsOut(
        total_jobs=total or 0,
        active_jobs=active or 0,
        pending_jobs=pending or 0,
        total_views=int(views or 0),
        total_apply_clicks=int(clicks or 0),
    )
