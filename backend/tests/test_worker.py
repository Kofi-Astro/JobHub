"""Worker tasks: source dispatch (incl. overlap/stuck-run protection), global
staleness expiry, and saved-search alerts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import respx
from sqlalchemy import select

from app.models import AlertDelivery, Job, SavedSearch, Source, SourceRun, User
from app.models.enums import (
    AlertDeliveryStatus,
    AlertFrequency,
    JobOrigin,
    JobStatus,
    SourceRunStatus,
    UserRole,
)
from app.services.auth import hash_password
from app.services.search import job_query_from_dict
from app.worker.tasks import (
    dispatch_due_sources,
    expire_globally_stale_jobs,
    send_due_alerts,
)
from tests.conftest_ingestion import load_fixture


def _source(db, key):
    return db.scalar(select(Source).where(Source.key == key))


def _disable_other_sources(db, *keep_keys):
    """`dispatch_due_sources` iterates every enabled source; the seed data
    enables several. Tests that only care about one or two sources disable
    the rest first, so a bug wouldn't have every seeded adapter racing off to
    hit (mocked-or-not) real networks in the same call."""
    for s in db.scalars(select(Source)):
        if s.key not in keep_keys:
            s.enabled = False
    db.flush()


# ---------------------------------------------------------------------------
# dispatch_due_sources
# ---------------------------------------------------------------------------


@respx.mock
def test_dispatch_runs_due_source_and_skips_not_due(seeded):
    db = seeded
    respx.get("https://remotive.com/api/remote-jobs").respond(json=load_fixture("remotive.json"))

    _disable_other_sources(db, "remotive", "remoteok")
    remotive = _source(db, "remotive")
    remotive.last_run_at = None  # never run -> due
    remoteok = _source(db, "remoteok")
    remoteok.last_run_at = datetime.now(UTC)  # just ran, interval not elapsed
    remoteok.refresh_interval_minutes = 360
    db.flush()

    triggered = dispatch_due_sources(db)

    assert "remotive" in triggered
    assert "remoteok" not in triggered
    db.refresh(remotive)
    assert remotive.last_run_at is not None


def test_dispatch_skips_a_source_with_a_run_already_in_flight(seeded):
    db = seeded
    _disable_other_sources(db, "remotive")
    src = _source(db, "remotive")
    src.last_run_at = None
    db.add(
        SourceRun(
            source_id=src.id,
            started_at=datetime.now(UTC),
            status=SourceRunStatus.RUNNING,
        )
    )
    db.commit()

    triggered = dispatch_due_sources(db)
    assert "remotive" not in triggered


@respx.mock
def test_dispatch_reaps_a_stuck_run_and_retries(seeded):
    db = seeded
    _disable_other_sources(db, "remotive")
    respx.get("https://remotive.com/api/remote-jobs").respond(json=load_fixture("remotive.json"))
    src = _source(db, "remotive")
    src.last_run_at = None
    stuck = SourceRun(
        source_id=src.id,
        started_at=datetime.now(UTC) - timedelta(hours=5),  # well past STUCK_RUN_TIMEOUT
        status=SourceRunStatus.RUNNING,
    )
    db.add(stuck)
    db.commit()

    triggered = dispatch_due_sources(db)

    assert "remotive" in triggered
    db.refresh(stuck)
    assert stuck.status == SourceRunStatus.FAILED


def test_dispatch_skips_disabled_sources(seeded):
    db = seeded
    _disable_other_sources(db)  # disable everything, including remotive
    src = _source(db, "remotive")
    src.last_run_at = None
    db.commit()

    assert dispatch_due_sources(db) == []


# ---------------------------------------------------------------------------
# expire_globally_stale_jobs
# ---------------------------------------------------------------------------


def _job(db, source_key, *, external_id, last_seen_at):
    src = _source(db, source_key)
    j = Job(
        origin=JobOrigin.AGGREGATED,
        source_id=src.id,
        external_id=external_id,
        title="x",
        company_name_raw="Acme",
        description_text="",
        status=JobStatus.ACTIVE,
        last_seen_at=last_seen_at,
    )
    db.add(j)
    db.flush()
    return j


def test_expire_globally_stale_jobs(seeded):
    db = seeded
    stale = _job(
        db, "remotive", external_id="stale-1", last_seen_at=datetime.now(UTC) - timedelta(days=30)
    )
    fresh = _job(db, "remotive", external_id="fresh-1", last_seen_at=datetime.now(UTC))
    never_seen = _job(db, "remotive", external_id="never-1", last_seen_at=None)
    db.commit()

    count = expire_globally_stale_jobs(db)

    assert count == 2
    db.refresh(stale)
    db.refresh(fresh)
    db.refresh(never_seen)
    assert stale.status == JobStatus.EXPIRED
    assert never_seen.status == JobStatus.EXPIRED
    assert fresh.status == JobStatus.ACTIVE


# ---------------------------------------------------------------------------
# job_query_from_dict
# ---------------------------------------------------------------------------


def test_job_query_from_dict_maps_frontend_keys():
    q = job_query_from_dict(
        {
            "q": "python",
            "field": ["computing-tech"],
            "remote": True,
            "salary_min": 50000,
            "bogus_future_key": "x",
        }
    )
    assert q.q == "python"
    assert q.field_slugs == ["computing-tech"]
    assert q.is_remote is True
    assert q.salary_min == 50000


# ---------------------------------------------------------------------------
# send_due_alerts
# ---------------------------------------------------------------------------


def _seeker(db, email="alerts@example.com"):
    u = User(role=UserRole.SEEKER, email=email, password_hash=hash_password("hunter2pass"))
    db.add(u)
    db.flush()
    return u


def test_alert_sends_only_for_jobs_newer_than_watermark(seeded, monkeypatch):
    db = seeded
    sent = []
    monkeypatch.setattr(
        "app.worker.tasks.send_email", lambda to, subject, body: sent.append((to, subject))
    )

    user = _seeker(db)
    old_job = _job(db, "remotive", external_id="old", last_seen_at=datetime.now(UTC))
    old_job.posted_at = datetime.now(UTC) - timedelta(days=10)
    new_job = _job(db, "remotive", external_id="new", last_seen_at=datetime.now(UTC))
    new_job.posted_at = datetime.now(UTC)
    db.flush()

    saved_search = SavedSearch(
        user_id=user.id,
        name="Anything",
        query_params={},
        alert_enabled=True,
        alert_frequency=AlertFrequency.DAILY,
        alert_high_water_mark=datetime.now(UTC) - timedelta(days=1),
    )
    db.add(saved_search)
    db.commit()

    counts = send_due_alerts(db)

    assert counts["sent"] == 1
    assert len(sent) == 1 and sent[0][0] == "alerts@example.com"
    db.refresh(saved_search)
    assert saved_search.last_alerted_at is not None
    assert saved_search.alert_high_water_mark == new_job.posted_at

    deliveries = db.scalars(select(AlertDelivery)).all()
    assert len(deliveries) == 1
    assert deliveries[0].status == AlertDeliveryStatus.SENT
    assert deliveries[0].job_count == 1


def test_alert_not_due_yet_is_skipped(seeded, monkeypatch):
    db = seeded
    sent = []
    monkeypatch.setattr("app.worker.tasks.send_email", lambda *a, **k: sent.append(a))
    user = _seeker(db)
    saved_search = SavedSearch(
        user_id=user.id,
        name="x",
        query_params={},
        alert_enabled=True,
        alert_frequency=AlertFrequency.WEEKLY,
        last_alerted_at=datetime.now(UTC) - timedelta(days=1),  # not a week yet
    )
    db.add(saved_search)
    db.commit()

    counts = send_due_alerts(db)
    assert counts["checked"] == 0
    assert not sent


def test_alert_with_no_new_jobs_is_logged_as_skipped_not_sent(seeded, monkeypatch):
    db = seeded
    monkeypatch.setattr(
        "app.worker.tasks.send_email",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not send")),
    )
    user = _seeker(db)
    saved_search = SavedSearch(
        user_id=user.id,
        name="x",
        query_params={"q": "nonexistent-term-xyz"},
        alert_enabled=True,
        alert_frequency=AlertFrequency.DAILY,
    )
    db.add(saved_search)
    db.commit()

    counts = send_due_alerts(db)
    assert counts["skipped"] == 1 and counts["sent"] == 0
