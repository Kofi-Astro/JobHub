"""Job-seeker state: `saved_jobs`, `saved_searches`, `alert_deliveries`.

Only *logged-in* seekers get rows here. Anonymous seekers get the same
capabilities backed by `localStorage` on the frontend; on first login the
frontend calls `POST /api/seeker/merge-anon` to fold that local state into these
tables once.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AlertDeliveryStatus, AlertFrequency, pg_enum


class SavedJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "saved_jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_saved_jobs_user_id_job_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job: Mapped[Any] = relationship("Job", lazy="joined")

    # Optional private note the seeker attaches ("referred by Sam", "applied 5/2").
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class SavedSearch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named, re-runnable search. An *alert* is just this row with
    `alert_enabled = true` — not a separate concept — because the thing being
    alerted on is exactly a saved search."""

    __tablename__ = "saved_searches"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # The serialized filter/search state (same shape the frontend puts in the
    # URL query string). Opaque to the DB; interpreted by the search service.
    query_params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # --- Alerting --------------------------------------------------------------
    alert_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    alert_frequency: Mapped[AlertFrequency | None] = mapped_column(
        pg_enum(AlertFrequency, "alert_frequency"), nullable=True
    )
    # When the alert last fired, and the newest `posted_at` we had already told
    # the user about — together these let the worker send only genuinely new
    # matches without re-notifying.
    last_alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alert_high_water_mark: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    deliveries: Mapped[list[AlertDelivery]] = relationship(
        back_populates="saved_search", cascade="all, delete-orphan"
    )


class AlertDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Log of one alert email attempt — for the seeker's history and for
    debugging "I didn't get my alert" reports."""

    __tablename__ = "alert_deliveries"

    saved_search_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("saved_searches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    saved_search: Mapped[SavedSearch] = relationship(back_populates="deliveries")

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    job_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[AlertDeliveryStatus] = mapped_column(
        pg_enum(AlertDeliveryStatus, "alert_delivery_status"), nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
