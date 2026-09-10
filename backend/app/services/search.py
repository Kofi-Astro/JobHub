"""Job search: a `JobQuery` value-object → a SQLAlchemy `Select`.

WHY a value-object seam: every filter combination the frontend can express is
captured in `JobQuery`. Route handlers parse request params into a `JobQuery`;
this module turns that into SQL. Nothing else in the app knows *how* search
works, so swapping Postgres FTS for Meilisearch/Typesense later means
reimplementing `build_select()` (and `facet_counts()`), not touching routes,
schemas, saved-searches, or the worker.

Search backend for v1: PostgreSQL full-text search over the generated
`jobs.search_vector` column (title weighted A, company B, location C,
description D), blended with recency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import Select, and_, case, func, or_, select

from app.models import Field, Job, Subfield
from app.models.enums import (
    ExperienceLevel,
    JobOrigin,
    JobStatus,
    JobType,
    WorkplaceType,
)

SortOption = Literal["relevance", "recent", "salary"]

# Hours of work per period, for annualising salary so ranges from different
# `salary_period` values can be compared in one filter.
_PERIOD_TO_YEAR = {
    "year": 1,
    "month": 12,
    "week": 52,
    "day": 260,
    "hour": 2080,
}


@dataclass(slots=True)
class JobQuery:
    """Everything the search/listing endpoints can be asked for.

    All list fields are AND-across-dimensions, OR-within-a-dimension (choosing
    two countries widens the result; adding a job-type narrows it).
    """

    q: str | None = None

    field_slugs: list[str] = field(default_factory=list)
    subfield_slugs: list[str] = field(default_factory=list)

    country_codes: list[str] = field(default_factory=list)
    city: str | None = None
    workplace_types: list[WorkplaceType] = field(default_factory=list)
    is_remote: bool | None = None

    job_types: list[JobType] = field(default_factory=list)
    experience_levels: list[ExperienceLevel] = field(default_factory=list)

    # Salary filter is annualised before comparison; currency is not converted,
    # so results may mix currencies — documented, acceptable for v1.
    salary_min: int | None = None
    salary_max: int | None = None
    include_undisclosed_salary: bool = True

    posted_within_days: int | None = None

    # `source_keys` filters aggregated jobs by source; `employer_only` maps to
    # the "Direct from employer" choice in the Source filter.
    source_keys: list[str] = field(default_factory=list)
    employer_only: bool = False

    # Only meaningful when at least one job carries a non-null value (the
    # frontend hides the filter otherwise).
    visa_sponsorship: bool | None = None

    sort: SortOption = "relevance"
    page: int = 1
    page_size: int = 20

    @property
    def offset(self) -> int:
        return (max(self.page, 1) - 1) * self.page_size


# ---------------------------------------------------------------------------
# SQL building blocks
# ---------------------------------------------------------------------------


def _annualized(col) -> case:
    """`col` (a salary amount) scaled to a yearly figure using `salary_period`."""
    return case(
        *[
            (Job.salary_period == period, col * factor)
            for period, factor in _PERIOD_TO_YEAR.items()
        ],
        else_=col,
    )


def _tsquery(text: str):
    """`websearch_to_tsquery` — understands quoted phrases and OR, and never
    raises on odd input (unlike `to_tsquery`)."""
    return func.websearch_to_tsquery("english", text)


def base_active_filter():
    """Rows eligible to appear anywhere public: active, canonical, visible."""
    return and_(
        Job.status == JobStatus.ACTIVE,
        Job.is_canonical.is_(True),
    )


def _apply_filters(stmt: Select, q: JobQuery, *, skip: str | None = None) -> Select:
    """Attach every filter in `q` to `stmt`, except the dimension named `skip`
    (used by faceting to count "as if this filter were cleared")."""

    if q.q:
        stmt = stmt.where(Job.search_vector.op("@@")(_tsquery(q.q)))

    if skip != "field" and q.field_slugs:
        stmt = stmt.where(Job.field_id.in_(select(Field.id).where(Field.slug.in_(q.field_slugs))))
    if skip != "subfield" and q.subfield_slugs:
        stmt = stmt.where(
            Job.subfield_id.in_(select(Subfield.id).where(Subfield.slug.in_(q.subfield_slugs)))
        )

    if skip != "country" and q.country_codes:
        stmt = stmt.where(Job.country_code.in_([c.upper() for c in q.country_codes]))
    if q.city:
        stmt = stmt.where(Job.city.ilike(f"%{q.city}%"))
    if skip != "workplace" and q.workplace_types:
        stmt = stmt.where(Job.workplace_type.in_(q.workplace_types))
    if q.is_remote is not None:
        stmt = stmt.where(Job.is_remote.is_(q.is_remote))

    if skip != "job_type" and q.job_types:
        stmt = stmt.where(Job.job_type.in_(q.job_types))
    if skip != "experience" and q.experience_levels:
        stmt = stmt.where(Job.experience_level.in_(q.experience_levels))

    if skip != "salary" and (q.salary_min is not None or q.salary_max is not None):
        disclosed = Job.salary_is_disclosed.is_(True)
        lo = _annualized(Job.salary_max)  # top of the job's band vs the query floor
        hi = _annualized(Job.salary_min)  # bottom of the job's band vs the query ceiling
        cond = disclosed
        if q.salary_min is not None:
            cond = and_(cond, or_(lo.is_(None), lo >= q.salary_min))
        if q.salary_max is not None:
            cond = and_(cond, or_(hi.is_(None), hi <= q.salary_max))
        # "Never hidden": undisclosed rows stay unless the user opts out.
        if q.include_undisclosed_salary:
            cond = or_(cond, Job.salary_is_disclosed.is_(False))
        stmt = stmt.where(cond)

    if q.posted_within_days:
        cutoff = datetime.now(UTC) - timedelta(days=q.posted_within_days)
        stmt = stmt.where(Job.posted_at >= cutoff)

    if skip != "source":
        source_conds = []
        if q.source_keys:
            from app.models import Source

            source_conds.append(
                Job.source_id.in_(select(Source.id).where(Source.key.in_(q.source_keys)))
            )
        if q.employer_only:
            source_conds.append(Job.origin == JobOrigin.EMPLOYER)
        if source_conds:
            stmt = stmt.where(or_(*source_conds))

    if q.visa_sponsorship is not None:
        stmt = stmt.where(Job.visa_sponsorship.is_(q.visa_sponsorship))

    return stmt


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_select(q: JobQuery) -> Select:
    """A `Select` of `Job` rows for the current query, ordered + paginated,
    with the relationships the job-card serializer needs eagerly loaded."""
    stmt = select(Job).where(base_active_filter())
    stmt = _apply_filters(stmt, q)

    if q.sort == "recent" or (q.sort == "relevance" and not q.q):
        stmt = stmt.order_by(Job.posted_at.desc().nulls_last(), Job.id)
    elif q.sort == "salary":
        stmt = stmt.order_by(_annualized(Job.salary_max).desc().nulls_last(), Job.posted_at.desc())
    else:
        # Relevance with a query term: FTS rank first, recency as the
        # tie-breaker so equally-relevant results show the newest on top.
        rank = func.ts_rank_cd(Job.search_vector, _tsquery(q.q))
        stmt = stmt.order_by(rank.desc(), Job.posted_at.desc().nulls_last(), Job.id)

    # company / source / field / subfield are all many-to-one with lazy="joined"
    # on the model, so the card serializer's attribute access needs no extra
    # round-trips and there is no row multiplication.
    return stmt.limit(q.page_size).offset(q.offset)


def count_select(q: JobQuery) -> Select:
    """`SELECT count(*)` for the query (no ordering/pagination)."""
    stmt = select(func.count()).select_from(Job).where(base_active_filter())
    return _apply_filters(stmt, q)


def facet_select(q: JobQuery, dimension: str, group_col) -> Select:
    """`group_col, count(*)` for one facet, with that dimension's own filter
    removed so its option counts don't collapse to the current result set."""
    stmt = (
        select(group_col, func.count())
        .select_from(Job)
        .where(base_active_filter())
        .group_by(group_col)
    )
    return _apply_filters(stmt, q, skip=dimension)
