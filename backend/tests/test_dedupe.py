"""Cross-source dedupe: the same role from two sources collapses to one
canonical row, and the higher-priority source wins."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.ingestion.dedupe import assign_canonical, shadowed_listings
from app.models import Job, Source
from app.models.enums import JobOrigin, JobStatus


def _job(db, *, source_key: str, external_id: str, ingested: datetime, dhash: str) -> Job:
    src = db.scalar(select(Source).where(Source.key == source_key))
    job = Job(
        origin=JobOrigin.AGGREGATED,
        source_id=src.id,
        external_id=external_id,
        title="Senior Backend Engineer",
        company_name_raw="Acme",
        description_text="",
        status=JobStatus.ACTIVE,
        ingested_at=ingested,
        dedupe_hash=dhash,
    )
    db.add(job)
    db.flush()
    return job


def test_ats_row_beats_aggregator_row(seeded):
    db = seeded
    h = "hash-of-the-role"
    # Aggregator sees it first...
    agg = _job(
        db,
        source_key="remotive",
        external_id="r1",
        ingested=datetime(2026, 9, 1, tzinfo=UTC),
        dhash=h,
    )
    assign_canonical(db, agg)
    assert agg.is_canonical is True

    # ...then the company's Greenhouse board (priority 50 > 10) lists it too.
    ats = _job(
        db,
        source_key="greenhouse",
        external_id="g1",
        ingested=datetime(2026, 9, 2, tzinfo=UTC),
        dhash=h,
    )
    assign_canonical(db, ats)

    db.flush()
    assert ats.is_canonical is True
    assert ats.canonical_job_id is None
    assert agg.is_canonical is False
    assert agg.canonical_job_id == ats.id
    assert {j.id for j in shadowed_listings(db, ats)} == {agg.id}


def test_same_priority_older_listing_wins(seeded):
    db = seeded
    h = "same-priority-hash"
    older = _job(
        db,
        source_key="remotive",
        external_id="a",
        ingested=datetime(2026, 9, 1, tzinfo=UTC),
        dhash=h,
    )
    assign_canonical(db, older)
    newer = _job(
        db,
        source_key="remoteok",
        external_id="b",
        ingested=datetime(2026, 9, 5, tzinfo=UTC),
        dhash=h,
    )
    assign_canonical(db, newer)

    db.flush()
    assert older.is_canonical is True
    assert newer.canonical_job_id == older.id


def test_unique_role_is_its_own_canonical(seeded):
    db = seeded
    solo = _job(
        db,
        source_key="remotive",
        external_id="solo",
        ingested=datetime(2026, 9, 1, tzinfo=UTC),
        dhash="unique",
    )
    assign_canonical(db, solo)
    assert solo.is_canonical is True and solo.canonical_job_id is None
