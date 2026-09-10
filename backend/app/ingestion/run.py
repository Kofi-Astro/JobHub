"""Ingestion CLI.

    python -m app.ingestion.run --source remotive     # one source
    python -m app.ingestion.run --all                  # every enabled source
    python -m app.ingestion.run --source greenhouse --dry-run   # fetch+normalize, no writes

Used for local development and one-off backfills. In production the worker
schedules `run_source()` per source on each source's `refresh_interval_minutes`.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.db.session import session_scope
from app.ingestion.normalize import normalize
from app.ingestion.pipeline import build_source_config, run_source
from app.ingestion.registry import get_adapter
from app.logging import configure_logging, get_logger
from app.models import Source

log = get_logger(__name__)


def _dry_run(source: Source) -> None:
    """Fetch + normalize and print a summary — no database writes."""
    adapter = get_adapter(source.adapter)
    config = build_source_config(source)
    seen = usable = 0
    samples = []
    for raw in adapter.fetch(config):
        seen += 1
        if not raw.is_usable():
            continue
        usable += 1
        n = normalize(raw)
        if len(samples) < 5:
            samples.append(
                f"  {n.title[:60]!r} @ {n.company_name_raw[:30]} "
                f"[{n.country_code or n.remote_scope or '—'}] "
                f"{n.job_type.value}/{n.experience_level.value}"
            )
    print(f"\n{source.key}: fetched {seen}, usable {usable}")
    print("\n".join(samples))


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Run JobHub ingestion.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source", help="source key (e.g. remotive)")
    group.add_argument("--all", action="store_true", help="run every enabled source")
    parser.add_argument("--dry-run", action="store_true", help="no DB writes; print a sample")
    args = parser.parse_args()

    with session_scope() as db:
        if args.all:
            sources = list(db.scalars(select(Source).where(Source.enabled.is_(True))))
        else:
            src = db.scalar(select(Source).where(Source.key == args.source))
            if src is None:
                sys.exit(f"unknown source {args.source!r}")
            sources = [src]

        for source in sources:
            if args.dry_run:
                _dry_run(source)
            else:
                run = run_source(db, source)
                print(
                    f"{source.key}: {run.status.value} "
                    f"(+{run.jobs_created} ~{run.jobs_updated} -{run.jobs_expired} "
                    f"!{run.jobs_failed})"
                )


if __name__ == "__main__":
    main()
