"""Worker entrypoint: `python -m app.worker.run`.

Starts the APScheduler event loop (see `scheduler.py`) that periodically
refreshes sources, expires stale jobs, and sends saved-search alerts, then
blocks until the process is asked to stop. This is the process the `worker`
Railway service (and the `worker` docker-compose service) runs — see
ARCHITECTURE.md's deployment section for why it's a separate process from the
API rather than a background thread inside it.
"""

from __future__ import annotations

import signal
import threading

from sqlalchemy import text

from app.db.session import engine
from app.logging import configure_logging, get_logger
from app.worker.scheduler import build_scheduler

log = get_logger(__name__)


def main() -> None:
    configure_logging()

    # Fail fast + loud if the database is unreachable — better than silently
    # scheduling jobs that will all error.
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    scheduler = build_scheduler()
    scheduler.start()
    log.info("worker.startup", jobs=[j.id for j in scheduler.get_jobs()])

    # Block until SIGINT/SIGTERM (Railway sends SIGTERM on redeploy).
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    stop.wait()

    scheduler.shutdown(wait=True)
    log.info("worker.shutdown")


if __name__ == "__main__":
    main()
