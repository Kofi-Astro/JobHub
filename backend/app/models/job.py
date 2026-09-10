"""`jobs` — the core table. Every listing, aggregated or employer-posted.

There is ONE jobs table on purpose. Aggregated and employer jobs are searched,
filtered, ranked and rendered by the exact same code; the only structural
difference is `origin` (+ which of `source_id` / `posted_by_user_id` is set).
This is what lets the brief's "side by side, no visual bias" requirement be true
by construction rather than by careful UI work.

Column groups below: identity/provenance, content, location, compensation,
classification, lifecycle, dedupe, search & metrics.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    CategorizationMethod,
    ExperienceLevel,
    JobOrigin,
    JobStatus,
    JobType,
    ModerationStatus,
    SalaryPeriod,
    WorkplaceType,
    pg_enum,
)


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # A source cannot list the same external id twice. `external_id` is
        # NULL for employer jobs, and Postgres treats NULLs as distinct, so this
        # only constrains aggregated rows — exactly what we want.
        UniqueConstraint("source_id", "external_id", name="uq_jobs_source_id_external_id"),
        # Structural integrity of the origin discriminator: an aggregated job
        # must have a source and no employer; an employer job the reverse.
        CheckConstraint(
            "(origin = 'aggregated' AND source_id IS NOT NULL AND posted_by_user_id IS NULL)"
            " OR "
            "(origin = 'employer' AND source_id IS NULL AND posted_by_user_id IS NOT NULL)",
            # The naming convention prepends "ck_jobs_"; keep this the bare suffix.
            name="origin_consistency",
        ),
        # Search index (Postgres FTS). GIN over the generated weighted tsvector.
        Index("ix_jobs_search_vector", "search_vector", postgresql_using="gin"),
        # The default listing order (newest active first) and the most common
        # filter columns. Compound where it pays off, single otherwise.
        Index("ix_jobs_status_posted_at", "status", "posted_at"),
        Index("ix_jobs_country_code", "country_code"),
        Index("ix_jobs_field_id", "field_id"),
        Index("ix_jobs_subfield_id", "subfield_id"),
        Index("ix_jobs_workplace_type", "workplace_type"),
        Index("ix_jobs_job_type", "job_type"),
        Index("ix_jobs_experience_level", "experience_level"),
        Index("ix_jobs_origin", "origin"),
        Index("ix_jobs_dedupe_hash", "dedupe_hash"),
        Index("ix_jobs_canonical_job_id", "canonical_job_id"),
        # The admin "needs categorization" queue — partial index keeps it tiny.
        Index(
            "ix_jobs_uncategorized",
            "is_uncategorized",
            postgresql_where="is_uncategorized",
        ),
        # Company drill-down / "more jobs at this company".
        Index("ix_jobs_company_id", "company_id"),
    )

    # ======================================================================
    # Identity / provenance
    # ======================================================================
    origin: Mapped[JobOrigin] = mapped_column(pg_enum(JobOrigin, "job_origin"), nullable=False)

    # Set when origin == aggregated.
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE")
    )
    source: Mapped[Any | None] = relationship("Source", lazy="joined")

    # Set when origin == employer — the employer account that created it.
    posted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL")
    )
    company: Mapped[Any | None] = relationship("Company", lazy="joined")

    # Identifier of this posting in the source system (used for upsert).
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Canonical URL of the posting on the source site.
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- The direct application path (brief: no gates, no middlemen) --------
    # Stored EXACTLY as the source/employer provides. At least one of url/email
    # must be present for the job to go active (enforced in the pipeline, not a
    # constraint, because a job can be ingested then enriched).
    apply_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    apply_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    apply_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Original payload from the source. Kept so the classifier / normalizer can
    # be re-run after a bug fix or keyword change without re-fetching.
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # ======================================================================
    # Content
    # ======================================================================
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    # Sanitized HTML (bleach allowlist) for rendering on the detail page.
    description_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Plaintext projection — drives full-text search and the keyword classifier.
    description_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Company name as given by the source, before `company_id` resolution.
    company_name_raw: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    # ======================================================================
    # Location — structured so any country works with no schema change
    # ======================================================================
    location_raw: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(200), nullable=True)
    region: Mapped[str | None] = mapped_column(String(200), nullable=True)  # state / province
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)  # ISO 3166-1 alpha-2
    country_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    is_remote: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    workplace_type: Mapped[WorkplaceType] = mapped_column(
        pg_enum(WorkplaceType, "workplace_type"),
        nullable=False,
        default=WorkplaceType.UNKNOWN,
    )
    # Free text like "Worldwide", "US only", "EU timezones" — shown on the card,
    # deliberately NOT a filter (too inconsistent across sources to filter on).
    remote_scope: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # ======================================================================
    # Compensation — missing data is flagged, never hidden (brief)
    # ======================================================================
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)  # ISO 4217
    salary_period: Mapped[SalaryPeriod | None] = mapped_column(
        pg_enum(SalaryPeriod, "salary_period"), nullable=True
    )
    # False ⇒ UI renders "Not disclosed". Explicit column (not "min IS NULL") so
    # an employer can actively choose "not disclosed" and we can tell the two
    # apart in analytics.
    salary_is_disclosed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ======================================================================
    # Classification
    # ======================================================================
    job_type: Mapped[JobType] = mapped_column(
        pg_enum(JobType, "job_type"), nullable=False, default=JobType.UNKNOWN
    )
    experience_level: Mapped[ExperienceLevel] = mapped_column(
        pg_enum(ExperienceLevel, "experience_level"),
        nullable=False,
        default=ExperienceLevel.UNKNOWN,
    )

    field_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("fields.id", ondelete="SET NULL")
    )
    subfield_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("subfields.id", ondelete="SET NULL")
    )
    categorization_method: Mapped[CategorizationMethod] = mapped_column(
        pg_enum(CategorizationMethod, "categorization_method"),
        nullable=False,
        default=CategorizationMethod.NONE,
    )
    categorization_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Set by the pipeline when the classifier abstains. A plain column (not
    # generated from `field_id IS NULL`) so an admin can clear it for a job that
    # is genuinely cross-cutting without being forced to assign a category.
    is_uncategorized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Visa sponsorship: NULLABLE, default NULL. ONLY ever written from the
    # employer posting checkbox. Aggregated ingestion must never set it (brief:
    # scraped visa data is unreliable and often wrong at the source).
    visa_sponsorship: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # ======================================================================
    # Lifecycle
    # ======================================================================
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"),
        nullable=False,
        default=JobStatus.ACTIVE,
    )
    moderation_status: Mapped[ModerationStatus] = mapped_column(
        pg_enum(ModerationStatus, "moderation_status"),
        nullable=False,
        default=ModerationStatus.NOT_REQUIRED,
    )

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Last ingestion run that still saw this job. Older than the run start after
    # a full successful sync ⇒ the job fell off the source ⇒ auto-expire.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ======================================================================
    # Dedupe (cross-source)
    # ======================================================================
    # sha1 of normalized(company | title | country_code | workplace_type).
    dedupe_hash: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # If this row is a duplicate, points at the canonical row; else NULL.
    canonical_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL")
    )
    # Denormalized "am I the one shown in search" flag (mirrors
    # canonical_job_id IS NULL) so the hot search query filters on one boolean.
    is_canonical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ======================================================================
    # Search & metrics
    # ======================================================================
    # Generated, STORED tsvector. Weights: title=A, company=B, location=C,
    # description=D — so a title hit ranks far above a description hit.
    # `to_tsvector('english', …)` is immutable with a literal config, which is
    # why Postgres permits it in a generated column.
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(company_name_raw, '')), 'B') || "
            "setweight(to_tsvector('english', coalesce(location_raw, '')), 'C') || "
            "setweight(to_tsvector('english', coalesce(description_text, '')), 'D')",
            persisted=True,
        ),
        nullable=False,
    )

    # Lightweight counters bumped by beacon endpoints. The authoritative history
    # is `analytics_events`; these are for fast display and coarse sorting.
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    apply_click_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Job {self.title!r} origin={self.origin} status={self.status}>"
