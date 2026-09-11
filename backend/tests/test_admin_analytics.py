"""Admin analytics summary: traffic, top searches, jobs per source, employer
activity — all windowed by `period_days`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import AnalyticsEvent
from app.models.enums import AnalyticsEventType


def test_analytics_requires_permission(client, seeded):
    assert client.get("/api/admin/analytics/summary").status_code == 401


def test_analytics_counts_events_within_the_window(client, seeded, admin_auth):
    db = seeded
    now = datetime.now(UTC)
    db.add(AnalyticsEvent(event_type=AnalyticsEventType.PAGE_VIEW, occurred_at=now))
    db.add(
        AnalyticsEvent(
            event_type=AnalyticsEventType.PAGE_VIEW, occurred_at=now - timedelta(days=40)
        )
    )  # outside 30d window
    db.add(
        AnalyticsEvent(
            event_type=AnalyticsEventType.SEARCH, occurred_at=now, properties={"q": "python"}
        )
    )
    db.add(
        AnalyticsEvent(
            event_type=AnalyticsEventType.SEARCH, occurred_at=now, properties={"q": "python"}
        )
    )
    db.add(
        AnalyticsEvent(
            event_type=AnalyticsEventType.SEARCH, occurred_at=now, properties={"q": "nurse"}
        )
    )
    db.add(AnalyticsEvent(event_type=AnalyticsEventType.JOB_VIEW, occurred_at=now))
    db.add(AnalyticsEvent(event_type=AnalyticsEventType.APPLY_CLICK, occurred_at=now))
    db.add(AnalyticsEvent(event_type=AnalyticsEventType.SEEKER_SIGNUP, occurred_at=now))
    db.add(AnalyticsEvent(event_type=AnalyticsEventType.EMPLOYER_SIGNUP, occurred_at=now))
    db.commit()

    body = client.get("/api/admin/analytics/summary?period_days=30", headers=admin_auth).json()

    assert body["page_views"] == 1  # the 40-day-old one is excluded
    assert body["searches"] == 3
    assert body["job_views"] == 1
    assert body["apply_clicks"] == 1
    assert body["seeker_signups"] == 1
    assert body["employer_signups"] == 1
    top = {row["q"]: row["count"] for row in body["top_searches"]}
    assert top["python"] == 2 and top["nurse"] == 1


def test_job_posting_records_an_analytics_event_admin_can_see(client, seeded, admin_auth):
    emp = client.post(
        "/api/auth/register/employer",
        json={"email": "poster@acme.example", "password": "hunter2pass", "company_name": "Acme"},
    )
    token = emp.json()["access_token"]
    client.post(
        "/api/employer/jobs",
        json={
            "title": "Backend Engineer",
            "description_html": "<p>x</p>",
            "field_slug": "computing-tech",
            "subfield_slug": "software-engineering",
            "workplace_type": "remote",
            "job_type": "full_time",
            "apply_url": "https://acme.example/apply",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    body = client.get("/api/admin/analytics/summary", headers=admin_auth).json()
    assert body["jobs_posted_by_employers"] == 1
