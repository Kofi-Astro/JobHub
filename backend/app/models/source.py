"""`sources` and `source_runs` — the adapter registry and its run history.

WHY these are tables, not code (from the brief): an admin must be able to add a
source, disable a flaky one, flip a source from the free tier to a paid tier, and
rotate rate limits — all without a deploy. Adapter *logic* stays in code
(`app/ingestion/adapters/`); everything an operator tunes lives in a `sources`
row.
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
from app.models.enums import SourceKind, SourceRunStatus, SourceTier, pg_enum


class Source(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sources"

    # --- Identity ----------------------------------------------------------
    # `key` is the stable machine name used in CLI commands, logs, and the
    # public "Source" filter. `adapter` is which adapter class runs it — many
    # rows can share one adapter (every Greenhouse board is adapter="greenhouse"
    # with a different `config.board_token`).
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    adapter: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[SourceKind] = mapped_column(pg_enum(SourceKind, "source_kind"), nullable=False)

    # --- Operational config (all admin-tunable) --------------------------------
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tier: Mapped[SourceTier] = mapped_column(
        pg_enum(SourceTier, "source_tier"), nullable=False, default=SourceTier.FREE
    )

    # `base_url` overrides the adapter's built-in default endpoint if set.
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Adapter-specific settings: Greenhouse board tokens, Adzuna country codes,
    # Lever company slugs, per-run result caps, etc. Free-form by design so a new
    # adapter never needs a schema change.
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # --- Credentials (indirection only — no secrets in the DB) ----------------
    requires_api_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Name of the environment variable / Railway secret holding the key. The
    # value is resolved at run time by `Settings.resolve_api_key()`.
    api_key_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- Rate limiting / scheduling -----------------------------------------
    rate_limit_per_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # How often the worker schedules this source (minutes). 360 = every 6h.
    refresh_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=360)

    # Dedupe tie-breaker: when the same posting appears from two sources, the
    # higher priority becomes the canonical row. Seeded employer=100, ats=50,
    # aggregator=10 (see sources_seed.py / dedupe.py).
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=10)

    # --- Health surface (written by each run) --------------------------------
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Drives exponential backoff and the admin "source down" alert.
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    runs: Mapped[list[SourceRun]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Source {self.key} enabled={self.enabled} tier={self.tier}>"


class SourceRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One ingestion run. The admin "sync health / error logs" screen is a list
    of these. Kept append-only; old rows are pruned by a worker task."""

    __tablename__ = "source_runs"
    __table_args__ = (
        UniqueConstraint("source_id", "started_at", name="uq_source_runs_source_id_started_at"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[Source] = relationship(back_populates="runs")

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[SourceRunStatus] = mapped_column(
        pg_enum(SourceRunStatus, "source_run_status"), nullable=False
    )

    # Counters for the run — what the admin dashboard graphs.
    jobs_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_expired: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Structured detail: per-board results, first N failing payloads, timings.
    log: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
