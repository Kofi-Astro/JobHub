"""Employer-submitted job postings.

This is the "employer submissions enter the pipeline at the normalization/
categorization stage" boundary described in ARCHITECTURE.md — but unlike
aggregated ingestion, the input here is already clean, typed, and validated by
`JobPostIn` (a human filled out a form), so there is no RawJob/guessing step.
What IS shared with the aggregated path: HTML sanitizing, the dedupe hash, and
`assign_canonical` — the same identity and de-duplication rules apply to every
job in the table regardless of where it came from.

Moderation (brief: "new employer accounts and/or first-time postings flagged
for admin approval before going live"): a posting needs review if EITHER the
employer's account is not yet approved OR this is their first-ever approved
posting. Once an employer has at least one approved posting and an approved
account, later postings go live immediately.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ingestion.dedupe import assign_canonical
from app.ingestion.normalize import (
    compute_dedupe_hash,
    country_name_for_code,
    html_to_text,
    sanitize_html,
)
from app.models import EmployerProfile, Field, Job, Subfield
from app.models.enums import (
    CategorizationMethod,
    EmployerAccountStatus,
    JobOrigin,
    JobStatus,
    ModerationStatus,
    WorkplaceType,
)
from app.schemas.employer import JobPostIn, JobPostUpdateIn
from app.schemas.jobs import location_label
from app.util.text import normalize_company_name


class EmployerJobError(ValueError):
    """Raised for a request the route layer should turn into 4xx, not 500."""


def _resolve_taxonomy(db: Session, field_slug: str, subfield_slug: str) -> tuple[Field, Subfield]:
    field = db.scalar(select(Field).where(Field.slug == field_slug, Field.is_active.is_(True)))
    if field is None:
        raise EmployerJobError(f"Unknown field {field_slug!r}.")
    subfield = db.scalar(
        select(Subfield).where(
            Subfield.slug == subfield_slug,
            Subfield.field_id == field.id,
            Subfield.is_active.is_(True),
        )
    )
    if subfield is None:
        raise EmployerJobError(f"Unknown sub-field {subfield_slug!r} under {field_slug!r}.")
    return field, subfield


def _posting_needs_moderation(db: Session, profile: EmployerProfile) -> bool:
    if profile.account_status != EmployerAccountStatus.APPROVED:
        return True
    has_prior_approved = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(
            Job.posted_by_user_id == profile.user_id,
            Job.moderation_status == ModerationStatus.APPROVED,
        )
    )
    return not has_prior_approved


def check_posting_quota(db: Session, profile: EmployerProfile) -> None:
    """`posting_quota` is NULL = unlimited (v1 default) — the paid-tier hook
    from ARCHITECTURE.md. Only enforced once a quota is actually set."""
    if profile.posting_quota is None:
        return
    active_count = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(
            Job.posted_by_user_id == profile.user_id,
            Job.status.in_([JobStatus.ACTIVE, JobStatus.PENDING]),
        )
    )
    if active_count >= profile.posting_quota:
        raise EmployerJobError(
            f"You've reached your posting limit ({profile.posting_quota}). "
            "Close an existing listing or upgrade your plan."
        )


def create_employer_job(db: Session, profile: EmployerProfile, data: JobPostIn) -> Job:
    check_posting_quota(db, profile)
    field, subfield = _resolve_taxonomy(db, data.field_slug, data.subfield_slug)

    needs_review = _posting_needs_moderation(db, profile)
    now = datetime.now(UTC)

    job = Job(
        origin=JobOrigin.EMPLOYER,
        posted_by_user_id=profile.user_id,
        company_id=profile.company_id,
        company_name_raw=profile.company.name if profile.company else "",
        title=data.title,
        description_html=sanitize_html(data.description_html),
        description_text=html_to_text(data.description_html),
        workplace_type=data.workplace_type,
        is_remote=data.workplace_type == WorkplaceType.REMOTE,
        city=data.city,
        region=data.region,
        country_code=(data.country_code or "").upper() or None,
        country_name=data.country_name or country_name_for_code(data.country_code),
        remote_scope=data.remote_scope,
        job_type=data.job_type,
        experience_level=data.experience_level,
        salary_is_disclosed=data.salary_is_disclosed,
        salary_min=data.salary_min if data.salary_is_disclosed else None,
        salary_max=data.salary_max if data.salary_is_disclosed else None,
        salary_currency=(data.salary_currency or "").upper() or None
        if data.salary_is_disclosed
        else None,
        salary_period=data.salary_period if data.salary_is_disclosed else None,
        apply_url=data.apply_url,
        apply_email=data.apply_email,
        apply_instructions=data.apply_instructions,
        visa_sponsorship=data.visa_sponsorship,
        field_id=field.id,
        subfield_id=subfield.id,
        categorization_method=CategorizationMethod.EMPLOYER,
        is_uncategorized=False,
        status=JobStatus.PENDING if needs_review else JobStatus.ACTIVE,
        moderation_status=ModerationStatus.PENDING if needs_review else ModerationStatus.APPROVED,
        posted_at=now,
        ingested_at=now,
        last_seen_at=now,
    )
    job.location_raw = location_label(job)
    job.dedupe_hash = compute_dedupe_hash(
        normalize_company_name(job.company_name_raw), job.title, job.country_code
    )

    db.add(job)
    db.flush()
    if job.status == JobStatus.ACTIVE:
        # Only a live job should compete for canonical status; a pending one
        # stays invisible either way (base_active_filter excludes non-ACTIVE).
        assign_canonical(db, job)
    db.commit()
    return job


def update_employer_job(db: Session, job: Job, data: JobPostUpdateIn) -> Job:
    updates = data.model_dump(exclude_unset=True)

    if "field_slug" in updates or "subfield_slug" in updates:
        field, subfield = _resolve_taxonomy(
            db,
            updates.get("field_slug") or job.field.slug,
            updates.get("subfield_slug") or job.subfield.slug,
        )
        job.field_id, job.subfield_id = field.id, subfield.id
        updates.pop("field_slug", None)
        updates.pop("subfield_slug", None)

    for attr, value in updates.items():
        setattr(job, attr, value)

    if not job.salary_is_disclosed:
        job.salary_min = job.salary_max = job.salary_currency = job.salary_period = None
    job.is_remote = job.workplace_type == WorkplaceType.REMOTE
    job.location_raw = location_label(job)
    job.dedupe_hash = compute_dedupe_hash(
        normalize_company_name(job.company_name_raw), job.title, job.country_code
    )

    db.flush()
    if job.status == JobStatus.ACTIVE:
        assign_canonical(db, job)
    db.commit()
    return job


def close_employer_job(db: Session, job: Job) -> Job:
    job.status = JobStatus.CLOSED
    job.is_canonical = False  # a closed job must never be search's canonical pick
    db.commit()
    return job


def republish_employer_job(db: Session, job: Job) -> Job:
    """Re-list a closed job. Still subject to the same moderation rule as a
    fresh posting — closing and reopening is not a way around review."""
    if job.moderation_status == ModerationStatus.REJECTED:
        raise EmployerJobError("A rejected listing must be edited before republishing.")

    now = datetime.now(UTC)
    if job.moderation_status == ModerationStatus.APPROVED:
        job.status = JobStatus.ACTIVE
    else:
        job.status = JobStatus.PENDING
        job.moderation_status = ModerationStatus.PENDING
    job.posted_at = now
    job.last_seen_at = now
    db.flush()
    if job.status == JobStatus.ACTIVE:
        assign_canonical(db, job)
    db.commit()
    return job
