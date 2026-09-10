"""The ingestion pipeline: one source → stored, categorized, deduped jobs.

    fetch (adapter)  →  normalize  →  resolve company  →  upsert job
                                   →  categorize (aggregated only)
                                   →  assign canonical (dedupe)
    …then, only after a fully successful run: expire jobs the source stopped listing.

`run_source()` is the single entry point, used by both the CLI
(`python -m app.ingestion.run`) and the worker's scheduled refresh jobs. Every
run writes a `source_runs` row and updates the `sources` health columns, so the
admin "sync health" screen always reflects reality.

Employer submissions do NOT come through here — they are built as a
`NormalizedJob` by the employer API and enter at `store_normalized_job()` with
`origin=employer`, pre-categorized, moderation-gated.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.categorization.classifier import Classifier
from app.ingestion.base import SourceConfig
from app.ingestion.dedupe import assign_canonical
from app.ingestion.normalize import NormalizedJob, normalize
from app.ingestion.registry import get_adapter
from app.logging import get_logger
from app.models import Job, Source, SourceRun
from app.models.enums import (
    CategorizationMethod,
    JobOrigin,
    JobStatus,
    SourceRunStatus,
)
from app.services.companies import resolve_company

log = get_logger(__name__)

# Categorization is (re)applied only when the current category was set
# automatically or not at all — a human decision (ADMIN/EMPLOYER) is never
# overwritten by the classifier.
_RECLASSIFIABLE = {CategorizationMethod.NONE, CategorizationMethod.KEYWORD}


def build_source_config(source: Source) -> SourceConfig:
    """Frozen snapshot of a `sources` row for the adapter."""
    return SourceConfig(
        key=source.key,
        name=source.name,
        adapter=source.adapter,
        kind=source.kind,
        base_url=source.base_url,
        config=dict(source.config or {}),
        priority=source.priority,
        request_timeout_seconds=source.request_timeout_seconds,
        rate_limit_per_min=source.rate_limit_per_min,
        api_key_ref=source.api_key_ref,
    )


def run_source(db: Session, source: Source) -> SourceRun:
    """Fetch, normalize, store and dedupe every job for `source`; then expire
    the ones it no longer lists. Commits its own work. Returns the `SourceRun`.
    """
    run = SourceRun(
        source_id=source.id,
        started_at=datetime.now(UTC),
        status=SourceRunStatus.RUNNING,
        jobs_seen=0,
        jobs_created=0,
        jobs_updated=0,
        jobs_expired=0,
        jobs_failed=0,
    )
    db.add(run)
    # Persist the run immediately so an adapter-level failure (which rolls back
    # record work) still leaves a "this run happened and failed" audit row.
    db.commit()
    run_id = run.id
    run_started = run.started_at
    config = build_source_config(source)
    adapter = get_adapter(source.adapter)
    classifier = Classifier.from_db(db)

    seen = created = updated = failed = 0
    board_errors: list[str] = []
    status = SourceRunStatus.SUCCESS
    error: str | None = None

    try:
        for raw in adapter.fetch(config):
            seen += 1
            if not raw.is_usable():
                failed += 1
                continue
            try:
                normalized = normalize(raw)
                _job, was_created = store_normalized_job(
                    db,
                    normalized,
                    origin=JobOrigin.AGGREGATED,
                    source=source,
                    classifier=classifier,
                )
                created += was_created
                updated += not was_created
                # Commit in modest batches so a late failure keeps early progress
                # and long runs don't hold one giant transaction.
                if (created + updated) % 200 == 0:
                    db.commit()
            except Exception as exc:
                failed += 1
                if len(board_errors) < 10:
                    board_errors.append(f"{raw.external_id}: {exc!r}")
                log.warning("ingestion.record_failed", source=source.key, error=repr(exc))
        db.commit()
    except Exception as exc:
        db.rollback()
        run = db.get(SourceRun, run_id)  # reload after rollback expired it
        status = SourceRunStatus.FAILED
        error = repr(exc)
        log.error("ingestion.source_failed", source=source.key, error=error)

    # Partial: the adapter finished but some records / boards were unusable.
    if status == SourceRunStatus.SUCCESS and (failed or board_errors):
        status = SourceRunStatus.PARTIAL

    expired = 0
    if status == SourceRunStatus.SUCCESS:
        # Only a clean full run is trustworthy enough to expire jobs. A partial
        # run might just be missing a board this time.
        expired = expire_unseen(db, source, run_started)
        db.commit()

    _finalize(db, run, source, status, error, seen, created, updated, expired, failed, board_errors)
    db.commit()

    log.info(
        "ingestion.run_complete",
        source=source.key,
        status=status.value,
        seen=seen,
        created=created,
        updated=updated,
        expired=expired,
        failed=failed,
    )
    return run


def store_normalized_job(
    db: Session,
    normalized: NormalizedJob,
    *,
    origin: JobOrigin,
    source: Source | None = None,
    posted_by_user_id: object | None = None,
    classifier: Classifier | None = None,
) -> tuple[Job, bool]:
    """Upsert one `NormalizedJob`. Returns (job, created?).

    Shared by aggregated ingestion (origin=aggregated, `source` set) and the
    employer portal (origin=employer, `posted_by_user_id` set). For aggregated
    jobs, `classifier` assigns field/sub-field unless a human already set them.
    Employer jobs skip the classifier; the employer API sets `field_id` /
    `subfield_id` / `categorization_method=EMPLOYER` on the returned job itself.
    """
    now = datetime.now(UTC)
    company = resolve_company(db, normalized.company_name_raw)

    existing: Job | None = None
    if origin == JobOrigin.AGGREGATED and source is not None and normalized.external_id:
        existing = db.scalar(
            select(Job).where(
                Job.source_id == source.id,
                Job.external_id == normalized.external_id,
            )
        )

    job = existing or Job(
        origin=origin,
        source_id=source.id if source else None,
        posted_by_user_id=posted_by_user_id,
        external_id=normalized.external_id,
        ingested_at=now,
        status=JobStatus.ACTIVE if origin == JobOrigin.AGGREGATED else JobStatus.PENDING,
        # Column-level defaults are only applied at flush; set the ones we read
        # or branch on before flush explicitly.
        categorization_method=CategorizationMethod.NONE,
        is_uncategorized=True,
        is_canonical=True,
        view_count=0,
        apply_click_count=0,
    )

    # --- fields refreshed every sync ---
    job.company_id = company.id if company else job.company_id
    job.company_name_raw = normalized.company_name_raw
    job.source_url = normalized.source_url
    job.apply_url = normalized.apply_url
    job.apply_email = normalized.apply_email
    job.title = normalized.title
    job.description_html = normalized.description_html
    job.description_text = normalized.description_text
    job.location_raw = normalized.location_raw
    job.city = normalized.city
    job.region = normalized.region
    job.country_code = normalized.country_code
    job.country_name = normalized.country_name
    job.is_remote = normalized.is_remote
    job.workplace_type = normalized.workplace_type
    job.remote_scope = normalized.remote_scope
    job.salary_min = normalized.salary_min
    job.salary_max = normalized.salary_max
    job.salary_currency = normalized.salary_currency
    job.salary_period = normalized.salary_period
    job.salary_is_disclosed = normalized.salary_is_disclosed
    job.job_type = normalized.job_type
    job.experience_level = normalized.experience_level
    job.posted_at = normalized.posted_at or job.posted_at or now
    job.last_seen_at = now
    job.dedupe_hash = normalized.dedupe_hash
    job.raw = normalized.raw

    if existing is None:
        db.add(job)

    # --- categorization (aggregated only; never clobber a human decision) ---
    if (
        origin == JobOrigin.AGGREGATED
        and classifier is not None
        and job.categorization_method in _RECLASSIFIABLE
    ):
        result = classifier.classify(job.title, job.description_text)
        job.field_id = result.field_id
        job.subfield_id = result.subfield_id
        job.categorization_method = result.method
        job.categorization_confidence = result.confidence
        job.is_uncategorized = not result.is_categorized

    db.flush()
    assign_canonical(db, job)
    return job, existing is None


def expire_unseen(db: Session, source: Source, run_started: datetime) -> int:
    """Mark this source's `active` jobs that were not seen in the run as expired.

    Then repair dedupe: if a now-expired job was canonical, promote the best
    still-active row in its group.
    """
    stale = list(
        db.scalars(
            select(Job).where(
                Job.source_id == source.id,
                Job.status == JobStatus.ACTIVE,
                (Job.last_seen_at.is_(None)) | (Job.last_seen_at < run_started),
            )
        )
    )
    if not stale:
        return 0

    affected_hashes = {j.dedupe_hash for j in stale if j.dedupe_hash}
    db.execute(
        update(Job)
        .where(Job.id.in_([j.id for j in stale]))
        .values(status=JobStatus.EXPIRED, is_canonical=False, canonical_job_id=None)
    )
    db.flush()

    # Re-pick a canonical among any still-active rows sharing an affected hash.
    for dhash in affected_hashes:
        survivor = db.scalar(
            select(Job).where(Job.dedupe_hash == dhash, Job.status == JobStatus.ACTIVE)
        )
        if survivor is not None:
            assign_canonical(db, survivor)

    return len(stale)


def _finalize(
    db: Session,
    run: SourceRun,
    source: Source,
    status: SourceRunStatus,
    error: str | None,
    seen: int,
    created: int,
    updated: int,
    expired: int,
    failed: int,
    board_errors: list[str],
) -> None:
    now = datetime.now(UTC)
    run.finished_at = now
    run.status = status
    run.jobs_seen = seen
    run.jobs_created = created
    run.jobs_updated = updated
    run.jobs_expired = expired
    run.jobs_failed = failed
    run.error = error
    run.log = {"record_errors": board_errors} if board_errors else None

    source.last_run_at = now
    if status in (SourceRunStatus.SUCCESS, SourceRunStatus.PARTIAL):
        source.last_success_at = now
        source.consecutive_failures = 0
    else:
        source.last_error_at = now
        source.last_error = error
        source.consecutive_failures = (source.consecutive_failures or 0) + 1
