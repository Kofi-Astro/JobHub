"""Admin: basic analytics dashboard (brief: "traffic, top searches, jobs per
source, employer activity").

v1 queries `analytics_events` directly for a `period_days` window — no
pre-aggregation. At this scale that is fast enough and, more importantly,
simple: the day this table gets too large for a live query, only this one
function needs a rollup-table rewrite (see ARCHITECTURE.md's analytics note).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin_permission
from app.db import get_db
from app.models import AnalyticsEvent, Job, Source, User
from app.models.enums import AnalyticsEventType, JobOrigin
from app.schemas.admin_ops import AnalyticsSummaryOut

router = APIRouter(prefix="/api/admin/analytics", tags=["admin-analytics"])

_view = require_admin_permission("analytics.view")


def _count(db: Session, since: datetime, event_type: AnalyticsEventType) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(AnalyticsEvent)
            .where(AnalyticsEvent.event_type == event_type, AnalyticsEvent.occurred_at >= since)
        )
        or 0
    )


@router.get("/summary", response_model=AnalyticsSummaryOut)
def analytics_summary(
    period_days: int = Query(30, ge=1, le=365),
    admin: User = Depends(_view),
    db: Session = Depends(get_db),
) -> AnalyticsSummaryOut:
    since = datetime.now(UTC) - timedelta(days=period_days)

    # Built once and reused in SELECT/WHERE/GROUP BY: each `properties["q"]`
    # call binds a fresh `'q'` parameter, and Postgres's parser cannot tell two
    # separately-bound placeholders will hold the same value at execution time
    # — so a GROUP BY built from a *different* occurrence of the same-looking
    # expression is (correctly) rejected as not matching the SELECT list.
    search_query_expr = AnalyticsEvent.properties["q"].astext

    top_searches = db.execute(
        select(
            search_query_expr.label("q"),
            func.count().label("n"),
        )
        .where(
            AnalyticsEvent.event_type == AnalyticsEventType.SEARCH,
            AnalyticsEvent.occurred_at >= since,
            search_query_expr.isnot(None),
        )
        .group_by(search_query_expr)
        .order_by(func.count().desc())
        .limit(10)
    ).all()

    jobs_per_source = db.execute(
        select(Source.name, func.count(Job.id))
        .join(Job, Job.source_id == Source.id)
        .group_by(Source.name)
    ).all()
    employer_job_count = (
        db.scalar(select(func.count()).select_from(Job).where(Job.origin == JobOrigin.EMPLOYER))
        or 0
    )

    return AnalyticsSummaryOut(
        period_days=period_days,
        page_views=_count(db, since, AnalyticsEventType.PAGE_VIEW),
        searches=_count(db, since, AnalyticsEventType.SEARCH),
        job_views=_count(db, since, AnalyticsEventType.JOB_VIEW),
        apply_clicks=_count(db, since, AnalyticsEventType.APPLY_CLICK),
        top_searches=[{"q": q, "count": n} for q, n in top_searches],
        jobs_per_source=[{"source": name, "count": n} for name, n in jobs_per_source]
        + (
            [{"source": "Direct from employer", "count": employer_job_count}]
            if employer_job_count
            else []
        ),
        seeker_signups=_count(db, since, AnalyticsEventType.SEEKER_SIGNUP),
        employer_signups=_count(db, since, AnalyticsEventType.EMPLOYER_SIGNUP),
        jobs_posted_by_employers=_count(db, since, AnalyticsEventType.JOB_POST),
    )
