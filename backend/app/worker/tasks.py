"""The worker's scheduled jobs.

Each function here is a plain, synchronous, idempotent unit of work that takes
its own `Session` and commits its own changes — `scheduler.py` just calls them
on a timer. Being plain callables (not framework-specific task objects) is
deliberate: swapping APScheduler for Celery later means changing what calls
these, not rewriting them (see ARCHITECTURE.md's worker section).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.ingestion.pipeline import run_source
from app.logging import get_logger
from app.models import AlertDelivery, Job, SavedSearch, Source, SourceRun, User
from app.models.enums import AlertDeliveryStatus, AlertFrequency, JobStatus, SourceRunStatus
from app.services import search
from app.services.email import send_email

log = get_logger(__name__)

# A SourceRun stuck in RUNNING longer than this is treated as crashed (the
# worker process died mid-run) rather than "still in progress", so a bad
# deploy or an OOM kill can't permanently wedge a source.
STUCK_RUN_TIMEOUT = timedelta(hours=2)


# ---------------------------------------------------------------------------
# Source refresh dispatch
# ---------------------------------------------------------------------------


def _reap_stuck_runs(db: Session) -> None:
    cutoff = datetime.now(UTC) - STUCK_RUN_TIMEOUT
    db.execute(
        update(SourceRun)
        .where(SourceRun.status == SourceRunStatus.RUNNING, SourceRun.started_at < cutoff)
        .values(status=SourceRunStatus.FAILED, error="worker did not finish (reaped as stuck)")
    )
    db.commit()


def _is_running(db: Session, source: Source) -> bool:
    cutoff = datetime.now(UTC) - STUCK_RUN_TIMEOUT
    return (
        db.scalar(
            select(SourceRun.id).where(
                SourceRun.source_id == source.id,
                SourceRun.status == SourceRunStatus.RUNNING,
                SourceRun.started_at >= cutoff,
            )
        )
        is not None
    )


def dispatch_due_sources(db: Session) -> list[str]:
    """Run every enabled source whose `refresh_interval_minutes` has elapsed.

    Deliberately a single periodic "who's due?" check rather than one
    APScheduler job per source: admin changes to `enabled` /
    `refresh_interval_minutes` take effect on the next tick automatically,
    with no need to reconcile a dynamic job list or restart the worker.
    """
    _reap_stuck_runs(db)
    now = datetime.now(UTC)
    triggered: list[str] = []

    for source in db.scalars(select(Source).where(Source.enabled.is_(True))):
        if _is_running(db, source):
            continue
        due = source.last_run_at is None or (
            now - source.last_run_at >= timedelta(minutes=source.refresh_interval_minutes)
        )
        if not due:
            continue
        try:
            run_source(db, source)
            triggered.append(source.key)
        except Exception as exc:
            db.rollback()
            log.error("worker.dispatch_source_failed", source=source.key, error=repr(exc))

    return triggered


# ---------------------------------------------------------------------------
# Staleness expiry (safety net beyond per-run expire_unseen)
# ---------------------------------------------------------------------------


def expire_globally_stale_jobs(db: Session) -> int:
    """Expire any aggregated `active` job not seen in `STALE_JOB_EXPIRY_DAYS`,
    regardless of source. `pipeline.expire_unseen` already handles this per
    successful run; this catches jobs whose source has been failing, was
    disabled, or was removed entirely, so nothing lingers forever.
    """
    cutoff = datetime.now(UTC) - timedelta(days=get_settings().stale_job_expiry_days)
    stale_ids = list(
        db.scalars(
            select(Job.id).where(
                Job.status == JobStatus.ACTIVE,
                Job.source_id.isnot(None),
                (Job.last_seen_at.is_(None)) | (Job.last_seen_at < cutoff),
            )
        )
    )
    if not stale_ids:
        return 0
    db.execute(
        update(Job)
        .where(Job.id.in_(stale_ids))
        .values(status=JobStatus.EXPIRED, is_canonical=False, canonical_job_id=None)
    )
    db.commit()
    log.info("worker.expire_globally_stale", count=len(stale_ids))
    return len(stale_ids)


# ---------------------------------------------------------------------------
# Saved-search alerts
# ---------------------------------------------------------------------------

_FREQUENCY_DELTA = {
    AlertFrequency.DAILY: timedelta(days=1),
    AlertFrequency.WEEKLY: timedelta(weeks=1),
}


def _alert_is_due(saved_search: SavedSearch, now: datetime) -> bool:
    if saved_search.last_alerted_at is None:
        return True
    delta = _FREQUENCY_DELTA.get(saved_search.alert_frequency, timedelta(days=1))
    return now - saved_search.last_alerted_at >= delta


def send_due_alerts(db: Session) -> dict[str, int]:
    """For every enabled, due saved search: find jobs posted since the last
    check, email them if there are any, log the attempt either way."""
    now = datetime.now(UTC)
    counts = {"checked": 0, "sent": 0, "skipped": 0, "failed": 0}

    due = db.scalars(select(SavedSearch).where(SavedSearch.alert_enabled.is_(True))).all()
    for saved_search in due:
        if not _alert_is_due(saved_search, now):
            continue
        counts["checked"] += 1

        user = db.get(User, saved_search.user_id)
        if user is None or not user.is_active:
            continue

        query = search.job_query_from_dict(saved_search.query_params)
        query.page_size = 50  # an alert email is a digest, not the full result set
        rows = list(db.scalars(search.build_select(query)))
        watermark = saved_search.alert_high_water_mark
        new_rows = [
            j for j in rows if j.posted_at and (watermark is None or j.posted_at > watermark)
        ]

        status = AlertDeliveryStatus.SKIPPED
        error = None
        if new_rows:
            try:
                send_email(
                    user.email,
                    f'{len(new_rows)} new job{"s" if len(new_rows) != 1 else ""} for "{saved_search.name}"',
                    _alert_email_text(saved_search, new_rows),
                )
                status = AlertDeliveryStatus.SENT
                counts["sent"] += 1
            except Exception as exc:
                status = AlertDeliveryStatus.FAILED
                error = repr(exc)
                counts["failed"] += 1
        else:
            counts["skipped"] += 1

        saved_search.last_alerted_at = now
        newest_seen = max((j.posted_at for j in rows if j.posted_at), default=None)
        if newest_seen and (watermark is None or newest_seen > watermark):
            saved_search.alert_high_water_mark = newest_seen

        db.add(
            AlertDelivery(
                saved_search_id=saved_search.id,
                sent_at=now if status == AlertDeliveryStatus.SENT else None,
                job_count=len(new_rows),
                status=status,
                error=error,
            )
        )
        db.commit()

    return counts


def _alert_email_text(saved_search: SavedSearch, jobs: list[Job]) -> str:
    lines = [f'New matches for your saved search "{saved_search.name}":', ""]
    for j in jobs[:20]:
        lines.append(f"- {j.title} at {j.company_name_raw} — {j.apply_url or j.source_url}")
    if len(jobs) > 20:
        lines.append(f"...and {len(jobs) - 20} more.")
    return "\n".join(lines)
