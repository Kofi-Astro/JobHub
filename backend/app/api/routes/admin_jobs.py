"""Admin: general job management (brief: "manually edit/hide/unpublish any
listing, aggregated or employer-posted") and manual categorization for the
review queue `admin_taxonomy.uncategorized_jobs` surfaces.

Distinct from `routes/admin.py`'s employer moderation queue: that gate is
specifically "should this employer posting go live at all"; this is
"something is already live (or was) and needs a correction" — hiding a
scraped job that turned out to be spam, fixing a mis-typed title, etc.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Pagination, pagination, require_admin_permission
from app.db import get_db
from app.ingestion.dedupe import assign_canonical
from app.models import Field, Job, Subfield, User
from app.models.enums import CategorizationMethod, JobOrigin, JobStatus
from app.schemas.admin_ops import AdminJobOut, AdminJobUpdateIn, CategorizeIn
from app.schemas.common import Message, Page
from app.services.audit import log_action

router = APIRouter(prefix="/api/admin/jobs", tags=["admin-jobs"])

_manage = require_admin_permission("jobs.manage")


def _to_out(job: Job) -> AdminJobOut:
    return AdminJobOut(
        id=job.id,
        title=job.title,
        company_name=job.company.name if job.company else job.company_name_raw,
        origin=job.origin,
        status=job.status,
        is_uncategorized=job.is_uncategorized,
        source_key=job.source.key if job.source else None,
        view_count=job.view_count,
        apply_click_count=job.apply_click_count,
        created_at=job.created_at,
    )


@router.get("", response_model=Page[AdminJobOut])
def list_jobs(
    page: Pagination = Depends(pagination),
    status: JobStatus | None = None,
    origin: JobOrigin | None = None,
    q: str | None = None,
    admin: User = Depends(_manage),
    db: Session = Depends(get_db),
) -> Page[AdminJobOut]:
    stmt = select(Job)
    if status is not None:
        stmt = stmt.where(Job.status == status)
    if origin is not None:
        stmt = stmt.where(Job.origin == origin)
    if q:
        stmt = stmt.where(Job.title.ilike(f"%{q}%"))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Job.created_at.desc()).limit(page.page_size).offset(page.offset)
    ).all()
    return Page.build([_to_out(j) for j in rows], total, page.page, page.page_size)


def _job_or_404(db: Session, job_id: uuid.UUID) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@router.patch("/{job_id}", response_model=AdminJobOut)
def update_job(
    job_id: uuid.UUID,
    body: AdminJobUpdateIn,
    admin: User = Depends(_manage),
    db: Session = Depends(get_db),
) -> AdminJobOut:
    job = _job_or_404(db, job_id)
    before = {"title": job.title, "status": job.status.value}
    updates = body.model_dump(exclude_unset=True)
    for attr, value in updates.items():
        setattr(job, attr, value)
    if "status" in updates:
        # A manual status change also settles whether this row can be the
        # canonical one for its dedupe group (e.g. hiding it must not leave
        # search pointing at a hidden listing).
        job.is_canonical = job.status == JobStatus.ACTIVE
        if job.is_canonical:
            db.flush()
            assign_canonical(db, job)
    log_action(
        db,
        admin.id,
        "job.update",
        "job",
        job.id,
        before=before,
        after={k: str(v) for k, v in updates.items()},
    )
    db.commit()
    return _to_out(job)


@router.post("/{job_id}/hide", response_model=Message)
def hide_job(
    job_id: uuid.UUID, admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> Message:
    job = _job_or_404(db, job_id)
    job.status = JobStatus.HIDDEN
    job.is_canonical = False
    log_action(db, admin.id, "job.hide", "job", job.id)
    db.commit()
    return Message(detail="Job hidden.")


@router.post("/{job_id}/unhide", response_model=Message)
def unhide_job(
    job_id: uuid.UUID, admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> Message:
    job = _job_or_404(db, job_id)
    if job.status != JobStatus.HIDDEN:
        raise HTTPException(status_code=409, detail="Job is not hidden.")
    job.status = JobStatus.ACTIVE
    job.is_canonical = True
    db.flush()
    assign_canonical(db, job)
    log_action(db, admin.id, "job.unhide", "job", job.id)
    db.commit()
    return Message(detail="Job restored to active.")


@router.post("/{job_id}/categorize", response_model=Message)
def categorize_job(
    job_id: uuid.UUID,
    body: CategorizeIn,
    admin: User = Depends(_manage),
    db: Session = Depends(get_db),
) -> Message:
    """Manually place a job the classifier abstained on (or correct a wrong
    category) — the action the uncategorized-jobs queue exists to drive."""
    job = _job_or_404(db, job_id)
    field = db.scalar(select(Field).where(Field.slug == body.field_slug))
    subfield = db.scalar(
        select(Subfield).where(
            Subfield.slug == body.subfield_slug, Subfield.field_id == field.id if field else None
        )
    )
    if field is None or subfield is None:
        raise HTTPException(status_code=404, detail="Unknown field/sub-field.")

    job.field_id = field.id
    job.subfield_id = subfield.id
    job.categorization_method = CategorizationMethod.ADMIN
    job.is_uncategorized = False
    log_action(
        db,
        admin.id,
        "job.categorize",
        "job",
        job.id,
        after={"field_slug": body.field_slug, "subfield_slug": body.subfield_slug},
    )
    db.commit()
    return Message(detail="Job categorized.")
