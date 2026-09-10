"""Worker entrypoint.

WHAT: Starts the APScheduler event loop that periodically refreshes sources,
expires stale jobs, and sends saved-search alerts.

MILESTONE 1 NOTE: the schedule itself is added in milestone 12. For now this
process just boots cleanly, configures logging, verifies it can reach the
database, and idles — so `docker compose up` brings up a healthy `worker`
container from day one and later milestones only add jobs to the scheduler.
"""

from __future__ import annotations

import signal
import threading

from sqlalchemy import text

from app.db.session import engine
from app.logging import configure_logging, get_logger

log = get_logger(__name__)


def main() -> None:
    configure_logging()

    # Fail fast + loud if the database is unreachable — better than silently
    # scheduling jobs that will all error.
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    log.info("worker.startup", note="scheduler jobs are registered in milestone 12")

    # Block until SIGINT/SIGTERM (Railway sends SIGTERM on redeploy).
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    stop.wait()
    log.info("worker.shutdown")


if __name__ == "__main__":
    main()
