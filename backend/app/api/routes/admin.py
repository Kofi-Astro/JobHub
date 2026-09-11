"""Admin: the moderation queue (employer account + job posting approval).

This is the minimum admin surface the brief's moderation requirement needs to
actually function end to end; the rest of the admin panel (taxonomy, sources,
users, content, analytics) is built out once the core data flows are proven —
see ARCHITECTURE.md's build order.

Every route requires the `employers.moderate` permission (superadmin and
moderator, by default — see `services/authz.py`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin_permission
from app.db import get_db
from app.ingestion.dedupe import assign_canonical
from app.models import EmployerProfile, Job, User
from app.models.enums import EmployerAccountStatus, JobOrigin, JobStatus, ModerationStatus
from app.schemas.admin import PendingEmployerOut, PendingJobOut, RejectIn
from app.schemas.common import Message
from app.services.audit import log_action

router = APIRouter(prefix="/api/admin", tags=["admin"])

_moderate = require_admin_permission("employers.moderate")


# ---------------------------------------------------------------------------
# Employer accounts
# ---------------------------------------------------------------------------


@router.get("/employers/pending", response_model=list[PendingEmployerOut])
def pending_employers(
    admin: User = Depends(_moderate), db: Session = Depends(get_db)
) -> list[PendingEmployerOut]:
    rows = db.scalars(
        select(EmployerProfile)
        .join(User, User.id == EmployerProfile.user_id)
        .where(EmployerProfile.account_status == EmployerAccountStatus.PENDING)
        .order_by(EmployerProfile.created_at)
    ).all()
    return [
        PendingEmployerOut(
            user_id=p.user_id,
            email=p.user.email,
            full_name=p.user.full_name,
            company_id=p.company_id,
            company_name=p.company.name if p.company else "",
            job_title=p.job_title,
            account_status=p.account_status,
            created_at=p.created_at,
        )
        for p in rows
    ]


def _employer_or_404(db: Session, user_id: uuid.UUID) -> EmployerProfile:
    profile = db.get(EmployerProfile, user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Employer account not found.")
    return profile


@router.post("/employers/{user_id}/approve", response_model=Message)
def approve_employer(
    user_id: uuid.UUID, admin: User = Depends(_moderate), db: Session = Depends(get_db)
) -> Message:
    profile = _employer_or_404(db, user_id)
    before = {"account_status": profile.account_status.value}
    profile.account_status = EmployerAccountStatus.APPROVED
    profile.approved_by_id = admin.id
    profile.approved_at = datetime.now(UTC)
    log_action(
        db,
        admin.id,
        "employer.approve",
        "employer_profile",
        user_id,
        before=before,
        after={"account_status": "approved"},
    )
    db.commit()
    return Message(detail="Employer account approved.")


@router.post("/employers/{user_id}/reject", response_model=Message)
def reject_employer(
    user_id: uuid.UUID,
    body: RejectIn,
    admin: User = Depends(_moderate),
    db: Session = Depends(get_db),
) -> Message:
    profile = _employer_or_404(db, user_id)
    before = {"account_status": profile.account_status.value}
    profile.account_status = EmployerAccountStatus.REJECTED
    profile.rejection_reason = body.reason
    log_action(
        db,
        admin.id,
        "employer.reject",
        "employer_profile",
        user_id,
        before=before,
        after={"account_status": "rejected", "reason": body.reason},
    )
    db.commit()
    return Message(detail="Employer account rejected.")


# ---------------------------------------------------------------------------
# Employer job postings
# ---------------------------------------------------------------------------


@router.get("/jobs/pending", response_model=list[PendingJobOut])
def pending_jobs(
    admin: User = Depends(_moderate), db: Session = Depends(get_db)
) -> list[PendingJobOut]:
    rows = db.scalars(
        select(Job)
        .where(Job.origin == JobOrigin.EMPLOYER, Job.moderation_status == ModerationStatus.PENDING)
        .order_by(Job.created_at)
    ).all()
    out = []
    for j in rows:
        poster = db.get(User, j.posted_by_user_id) if j.posted_by_user_id else None
        out.append(
            PendingJobOut(
                id=j.id,
                title=j.title,
                company_name=j.company.name if j.company else j.company_name_raw,
                employer_email=poster.email if poster else "",
                status=j.status,
                moderation_status=j.moderation_status,
                created_at=j.created_at,
            )
        )
    return out


def _pending_employer_job_or_404(db: Session, job_id: uuid.UUID) -> Job:
    job = db.scalar(
        select(Job).where(
            Job.id == job_id,
            Job.origin == JobOrigin.EMPLOYER,
            Job.moderation_status == ModerationStatus.PENDING,
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Pending job posting not found.")
    return job


@router.post("/jobs/{job_id}/approve", response_model=Message)
def approve_job(
    job_id: uuid.UUID, admin: User = Depends(_moderate), db: Session = Depends(get_db)
) -> Message:
    job = _pending_employer_job_or_404(db, job_id)
    job.moderation_status = ModerationStatus.APPROVED
    job.status = JobStatus.ACTIVE
    db.flush()
    assign_canonical(db, job)
    log_action(db, admin.id, "job.approve", "job", job.id, after={"status": "active"})
    db.commit()
    return Message(detail="Job approved and published.")


@router.post("/jobs/{job_id}/reject", response_model=Message)
def reject_job(
    job_id: uuid.UUID,
    body: RejectIn,
    admin: User = Depends(_moderate),
    db: Session = Depends(get_db),
) -> Message:
    job = _pending_employer_job_or_404(db, job_id)
    job.moderation_status = ModerationStatus.REJECTED
    job.status = JobStatus.REJECTED
    log_action(
        db,
        admin.id,
        "job.reject",
        "job",
        job.id,
        after={"status": "rejected", "reason": body.reason},
    )
    db.commit()
    return Message(detail="Job rejected.")
