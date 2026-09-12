"""`analytics_events` — the append-only event stream behind the admin dashboard.

WHAT: One row per meaningful user action (search, job view, apply click, signup,
job post). The admin "basic analytics dashboard" (traffic, top searches, jobs
per source, employer activity) is aggregates over this table.

WHY a raw event table for v1: it is the simplest thing that captures enough to
answer questions we haven't thought of yet. It is deliberately cheap to write
(no FKs enforced as required, minimal indexes). A later migration can partition
by month and roll up into summary tables if volume demands — the dashboard
queries are the only reader, so that change is contained.

`bigint` identity PK (not UUID): this is high-volume, ordered, append-only log
data — a monotonic integer is the right key and index.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import AnalyticsEventType, pg_enum


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    __table_args__ = (
        # The dashboard almost always slices "events of type X over time range".
        Index("ix_analytics_events_type_occurred", "event_type", "occurred_at"),
        # "activity for this job" / "this source" / "this employer".
        Index("ix_analytics_events_job_id", "job_id"),
        Index("ix_analytics_events_source_id", "source_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    event_type: Mapped[AnalyticsEventType] = mapped_column(
        pg_enum(AnalyticsEventType, "analytics_event_type"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Client-generated UUID (stored in localStorage, sent as X-Session-Id) that
    # ties an anonymous visitor's events together without a login or a cookie.
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Soft references — no FK constraint so a delete of the referenced row never
    # blocks, and event writes never need the target to still exist.
    user_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # Event-specific payload: {query, filters, result_count} for a search;
    # {referrer} for a page view; {apply_target} for an apply click; etc.
    properties: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
