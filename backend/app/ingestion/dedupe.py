"""Cross-source de-duplication.

The same role routinely appears on an aggregator (Remotive) AND on the company's
own ATS board (Greenhouse). We keep every row — provenance matters and a source
may carry extra detail — but only ONE row per real role is "canonical" and shown
in search/listings.

Grouping key: `jobs.dedupe_hash` (computed in `normalize.py` from company + title
+ country + workplace type — deliberately coarse; see that module).

Winner within a group:
    1. highest source `priority`  (employer 100 > ATS 50 > aggregator 10),
    2. tie → the listing we have known about longest (`ingested_at`),
    3. tie → lowest id (stable, arbitrary).

The winner gets `is_canonical = True`, `canonical_job_id = NULL`; everyone else
in the group points at the winner and is hidden from search. This runs after a
job row is inserted/updated, on just that job's group, so it is cheap.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Job
from app.models.enums import JobOrigin

# Priority used for employer-posted jobs (which have no `sources` row). Must stay
# above every seeded source priority so a direct employer listing always wins.
EMPLOYER_PRIORITY = 100


def _priority_of(job: Job) -> int:
    if job.origin == JobOrigin.EMPLOYER:
        return EMPLOYER_PRIORITY
    return job.source.priority if job.source is not None else 0


def _sort_key(job: Job) -> tuple:
    # Higher priority first; then older ingested_at; then smaller id.
    ingested = job.ingested_at.timestamp() if job.ingested_at else float("inf")
    return (-_priority_of(job), ingested, str(job.id))


def assign_canonical(db: Session, job: Job) -> None:
    """Recompute the canonical row for `job`'s dedupe group and repoint members.

    Mutates ORM objects in the session; the caller commits.
    """
    if not job.dedupe_hash:
        job.is_canonical = True
        job.canonical_job_id = None
        return

    siblings = list(
        db.scalars(
            select(Job).where(
                Job.dedupe_hash == job.dedupe_hash,
                Job.id != job.id,
            )
        )
    )
    group = [job, *siblings]

    # If the group is a singleton, `job` is trivially canonical.
    winner = min(group, key=_sort_key)

    for member in group:
        if member.id == winner.id:
            member.is_canonical = True
            member.canonical_job_id = None
        else:
            member.is_canonical = False
            member.canonical_job_id = winner.id


def shadowed_listings(db: Session, canonical_job: Job) -> list[Job]:
    """Every non-canonical row that points at `canonical_job` — used by the job
    detail page to show "also listed on: …"."""
    if not canonical_job.is_canonical:
        return []
    return list(db.scalars(select(Job).where(Job.canonical_job_id == canonical_job.id)))
