"""End-to-end ingestion pipeline tests: adapter → normalize → store → dedupe →
categorize → expire. HTTP is mocked (respx); the database is real."""

from __future__ import annotations

import httpx
import respx
from sqlalchemy import func, select

from app.ingestion.pipeline import run_source
from app.models import Job, Source, SourceRun
from app.models.enums import JobOrigin, JobStatus, SourceRunStatus
from tests.conftest_ingestion import load_fixture


def _source(db, key: str) -> Source:
    return db.scalar(select(Source).where(Source.key == key))


@respx.mock
def test_remotive_run_stores_categorizes_and_records(seeded):
    db = seeded
    respx.get("https://remotive.com/api/remote-jobs").respond(json=load_fixture("remotive.json"))

    run = run_source(db, _source(db, "remotive"))

    assert run.status == SourceRunStatus.SUCCESS
    assert run.jobs_seen == 2 and run.jobs_created == 2

    jobs = list(db.scalars(select(Job).where(Job.origin == JobOrigin.AGGREGATED)))
    assert len(jobs) == 2
    backend = next(j for j in jobs if "Backend" in j.title)
    assert backend.status == JobStatus.ACTIVE
    assert backend.is_remote is True
    assert backend.apply_url.startswith("https://remotive.com")
    assert backend.company_id is not None  # company row was resolved
    assert backend.field_id is not None  # keyword classifier placed it
    assert backend.search_vector is not None


@respx.mock
def test_second_run_updates_not_duplicates(seeded):
    db = seeded
    route = respx.get("https://remotive.com/api/remote-jobs")
    route.respond(json=load_fixture("remotive.json"))
    src = _source(db, "remotive")

    run_source(db, src)
    first_count = db.scalar(select(func.count()).select_from(Job))
    run2 = run_source(db, src)

    assert db.scalar(select(func.count()).select_from(Job)) == first_count
    assert run2.jobs_created == 0 and run2.jobs_updated == 2


@respx.mock
def test_job_dropped_by_source_is_expired(seeded):
    db = seeded
    route = respx.get("https://remotive.com/api/remote-jobs")
    src = _source(db, "remotive")

    full = load_fixture("remotive.json")
    route.respond(json=full)
    run_source(db, src)

    # Next sync: the source only lists the first job now.
    shrunk = {"jobs": [full["jobs"][0]]}
    route.respond(json=shrunk)
    run = run_source(db, src)

    assert run.jobs_expired == 1
    statuses = dict(db.execute(select(Job.title, Job.status)).all())
    assert any(s == JobStatus.EXPIRED for s in statuses.values())
    assert any(s == JobStatus.ACTIVE for s in statuses.values())


@respx.mock
def test_cross_source_dedupe_prefers_ats(seeded):
    db = seeded
    # Same role, same company, remote — from an aggregator and an ATS board.
    remotive_payload = {
        "jobs": [
            {
                "id": 42,
                "url": "https://remotive.com/x/42",
                "title": "Staff Software Engineer",
                "company_name": "Acme",
                "candidate_required_location": "United States",
                "publication_date": "2026-09-01T00:00:00",
                "description": "<p>Build things.</p>",
                "job_type": "full_time",
            }
        ]
    }
    gh_payload = {
        "jobs": [
            {
                "id": 99,
                "title": "Staff Software Engineer",
                "updated_at": "2026-09-02T00:00:00Z",
                "location": {"name": "United States"},
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/99",
                "content": "&lt;p&gt;Build things.&lt;/p&gt;",
                "departments": [{"name": "Engineering"}],
            }
        ]
    }
    respx.get("https://remotive.com/api/remote-jobs").respond(json=remotive_payload)
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true").respond(
        json=gh_payload
    )

    gh = _source(db, "greenhouse")
    gh.config = {"board_tokens": ["acme"]}
    db.flush()

    run_source(db, _source(db, "remotive"))
    run_source(db, gh)

    canonical = list(db.scalars(select(Job).where(Job.is_canonical.is_(True))))
    assert len(canonical) == 1
    assert canonical[0].source.key == "greenhouse"  # ATS (priority 50) wins


@respx.mock
def test_adapter_failure_marks_run_failed_and_bumps_counter(seeded):
    db = seeded
    respx.get("https://remotive.com/api/remote-jobs").mock(side_effect=httpx.ConnectError("boom"))
    src = _source(db, "remotive")

    run = run_source(db, src)

    assert run.status == SourceRunStatus.FAILED
    assert run.error is not None
    db.refresh(src)
    assert src.consecutive_failures == 1
    assert db.scalar(select(func.count()).select_from(SourceRun)) >= 1
