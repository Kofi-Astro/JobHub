"""APScheduler wiring: turns the plain functions in `tasks.py` into a running
schedule. Each job opens its own DB session (`session_scope`) so jobs never
share a session or a transaction with each other.

| Job                     | Interval | Does |
|--------------------------|----------|------|
| dispatch_due_sources     | 5 min    | runs any enabled source whose refresh interval has elapsed |
| expire_globally_stale    | 1 hour   | safety-net expiry beyond per-run expire_unseen |
| send_due_alerts          | 1 hour   | saved-search alert emails |

Why APScheduler (not Celery) — see ARCHITECTURE.md: no broker to run, and this
scale of periodic work doesn't need one. `BackgroundScheduler` runs jobs on a
thread pool inside this same process; `run.py` just has to stay alive.
"""

from __future__ import annotations

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler

from app.db.session import session_scope
from app.logging import get_logger
from app.worker import tasks

log = get_logger(__name__)


def _run(name, fn) -> None:
    """Wrap a task function: open a session, run it, log the outcome. A
    task's own exceptions are already handled internally where it matters
    (e.g. one bad source doesn't stop the others); this is the outer net for
    anything that still escapes, so APScheduler never silently drops a job."""
    try:
        with session_scope() as db:
            result = fn(db)
        log.info("worker.job_complete", job=name, result=result)
    except Exception as exc:
        log.error("worker.job_failed", job=name, error=repr(exc))


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(
        timezone="UTC",
        executors={"default": ThreadPoolExecutor(max_workers=4)},
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
    )

    scheduler.add_job(
        lambda: _run("dispatch_due_sources", tasks.dispatch_due_sources),
        "interval",
        minutes=5,
        id="dispatch_due_sources",
        next_run_time=_now_plus(seconds=10),  # a quick first pass shortly after boot
    )
    scheduler.add_job(
        lambda: _run("expire_globally_stale_jobs", tasks.expire_globally_stale_jobs),
        "interval",
        hours=1,
        id="expire_globally_stale_jobs",
    )
    scheduler.add_job(
        lambda: _run("send_due_alerts", tasks.send_due_alerts),
        "interval",
        hours=1,
        id="send_due_alerts",
    )
    return scheduler


def _now_plus(**kwargs):
    from datetime import UTC, datetime, timedelta

    return datetime.now(UTC) + timedelta(**kwargs)
