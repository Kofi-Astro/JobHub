"""Public job endpoints: search + filter + facets + detail + click beacons.

Everything here is anonymous — no account is needed to browse, search, view, or
apply. `X-Session-Id` (optional) links a visitor's analytics events.
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Pagination, pagination, session_id
from app.db import get_db
from app.ingestion.dedupe import shadowed_listings
from app.models import Field, Job, Source, Subfield
from app.models.enums import (
    AnalyticsEventType,
    ExperienceLevel,
    JobType,
    WorkplaceType,
)
from app.schemas.common import Page
from app.schemas.jobs import (
    ApplyTarget,
    FacetCount,
    JobCard,
    JobDetail,
    JobFacets,
)
from app.services import search
from app.services.analytics import record_event

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ---------------------------------------------------------------------------
# Query-param → JobQuery
# ---------------------------------------------------------------------------


def parse_job_query(
    page: Pagination = Depends(pagination),
    q: str | None = Query(None, description="full-text search"),
    field: list[str] = Query(default=[], description="field slug(s)"),
    subfield: list[str] = Query(default=[]),
    country: list[str] = Query(default=[], description="ISO 3166-1 alpha-2 code(s)"),
    city: str | None = Query(None),
    workplace: list[WorkplaceType] = Query(default=[]),
    remote: bool | None = Query(None),
    job_type: list[JobType] = Query(default=[]),
    experience: list[ExperienceLevel] = Query(default=[]),
    salary_min: int | None = Query(None, ge=0),
    salary_max: int | None = Query(None, ge=0),
    include_undisclosed_salary: bool = Query(True),
    posted_within_days: int | None = Query(None, ge=1, le=365),
    source: list[str] = Query(default=[], description="aggregated source key(s)"),
    employer_only: bool = Query(False, description='the "Direct from employer" source'),
    visa_sponsorship: bool | None = Query(None),
    sort: search.SortOption = Query("relevance"),
) -> search.JobQuery:
    return search.JobQuery(
        q=q.strip() if q else None,
        field_slugs=field,
        subfield_slugs=subfield,
        country_codes=country,
        city=city.strip() if city else None,
        workplace_types=list(workplace),
        is_remote=remote,
        job_types=list(job_type),
        experience_levels=list(experience),
        salary_min=salary_min,
        salary_max=salary_max,
        include_undisclosed_salary=include_undisclosed_salary,
        posted_within_days=posted_within_days,
        source_keys=source,
        employer_only=employer_only,
        visa_sponsorship=visa_sponsorship,
        sort=sort,
        page=page.page,
        page_size=page.page_size,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=Page[JobCard], summary="Search + filter jobs")
def list_jobs(
    query: search.JobQuery = Depends(parse_job_query),
    db: Session = Depends(get_db),
    sid: str | None = Depends(session_id),
) -> Page[JobCard]:
    total = db.scalar(search.count_select(query)) or 0
    rows = db.scalars(search.build_select(query)).all()

    # Record the search (best-effort, does not block the response).
    record_event(
        db,
        AnalyticsEventType.SEARCH,
        session_id=sid,
        properties={
            "q": query.q,
            "result_count": total,
            "filters": _active_filter_summary(query),
        },
    )
    return Page.build([JobCard.from_job(j) for j in rows], total, query.page, query.page_size)


# One grouped query per facet, cached briefly by the filter signature.
_FACET_CACHE: dict[str, tuple[float, JobFacets]] = {}
_FACET_TTL = 60.0


@router.get("/facets", response_model=JobFacets, summary="Live filter counts")
def job_facets(
    query: search.JobQuery = Depends(parse_job_query),
    db: Session = Depends(get_db),
) -> JobFacets:
    key = _facet_cache_key(query)
    hit = _FACET_CACHE.get(key)
    if hit and (time.monotonic() - hit[0]) < _FACET_TTL:
        return hit[1]

    total = db.scalar(search.count_select(query)) or 0

    # Look-up tables for turning ids/codes into labels.
    field_names = dict(db.execute(select(Field.id, Field.name)).all())
    field_slugs = dict(db.execute(select(Field.id, Field.slug)).all())
    subfield_meta = {
        sid_: (slug, name)
        for sid_, slug, name in db.execute(select(Subfield.id, Subfield.slug, Subfield.name)).all()
    }
    source_names = dict(db.execute(select(Source.id, Source.name)).all())

    facets = JobFacets(
        total=total,
        fields=_facet(
            db,
            query,
            "field",
            Job.field_id,
            lambda fid: (field_slugs.get(fid), field_names.get(fid)),
        ),
        subfields=_facet(
            db,
            query,
            "subfield",
            Job.subfield_id,
            lambda sid_: subfield_meta.get(sid_, (None, None)),
        ),
        workplace_types=_enum_facet(db, query, "workplace", Job.workplace_type),
        job_types=_enum_facet(db, query, "job_type", Job.job_type),
        experience_levels=_enum_facet(db, query, "experience", Job.experience_level),
        countries=_facet(db, query, "country", Job.country_code, lambda c: (c, c)),
        sources=_source_facet(db, query, source_names),
    )
    _FACET_CACHE[key] = (time.monotonic(), facets)
    return facets


@router.get("/{job_id}", response_model=JobDetail, summary="Full job detail")
def get_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> JobDetail:
    job = db.get(Job, job_id)
    if job is None or job.status.value in {"rejected", "pending"}:
        raise HTTPException(status_code=404, detail="Job not found.")

    # If the caller landed on a de-duplicated (shadow) row, serve the canonical
    # one so they see the best version and a stable URL.
    if not job.is_canonical and job.canonical_job_id:
        canonical = db.get(Job, job.canonical_job_id)
        if canonical is not None:
            job = canonical

    shadows = shadowed_listings(db, job)
    return JobDetail.from_job(job, shadows=shadows)


@router.post("/{job_id}/view", status_code=204, summary="Record a job view (beacon)")
def record_view(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    sid: str | None = Depends(session_id),
) -> Response:
    updated = db.execute(
        Job.__table__.update().where(Job.id == job_id).values(view_count=Job.view_count + 1)
    )
    if updated.rowcount:
        record_event(db, AnalyticsEventType.JOB_VIEW, session_id=sid, job_id=job_id, commit=False)
        db.commit()
    return Response(status_code=204)


@router.post(
    "/{job_id}/apply-click",
    response_model=ApplyTarget,
    summary="Record an apply click and return the application target",
)
def apply_click(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    sid: str | None = Depends(session_id),
) -> ApplyTarget:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    job.apply_click_count = (job.apply_click_count or 0) + 1
    record_event(
        db,
        AnalyticsEventType.APPLY_CLICK,
        session_id=sid,
        job_id=job.id,
        source_id=job.source_id,
        properties={"apply_url": job.apply_url},
        commit=False,
    )
    db.commit()
    return ApplyTarget(
        url=job.apply_url,
        email=job.apply_email,
        instructions=job.apply_instructions,
    )


# ---------------------------------------------------------------------------
# Facet helpers
# ---------------------------------------------------------------------------


def _facet(db, query, dimension, column, labeller) -> list[FacetCount]:
    """Count rows grouped by `column`, ignoring `dimension`'s own filter."""
    rows = db.execute(search.facet_select(query, dimension, column)).all()
    out: list[FacetCount] = []
    for value, count in rows:
        if value is None:
            continue
        slug, label = labeller(value)
        out.append(FacetCount(value=slug or str(value), label=label or str(value), count=count))
    return sorted(out, key=lambda f: f.count, reverse=True)


def _enum_facet(db, query, dimension, column) -> list[FacetCount]:
    rows = db.execute(search.facet_select(query, dimension, column)).all()
    return sorted(
        (
            FacetCount(
                value=v.value if hasattr(v, "value") else str(v),
                label=(v.value if hasattr(v, "value") else str(v)).replace("_", " ").title(),
                count=c,
            )
            for v, c in rows
            if v is not None
        ),
        key=lambda f: f.count,
        reverse=True,
    )


def _source_facet(db, query, source_names) -> list[FacetCount]:
    """Source facet = one row per aggregated source + a "Direct from employer"
    bucket for employer jobs."""
    rows = db.execute(search.facet_select(query, "source", Job.source_id)).all()
    employer_count = db.scalar(search.count_select(_with_employer_only(query))) or 0

    out = [
        FacetCount(
            value=str(sid_),
            label=source_names.get(sid_, "Aggregated"),
            count=c,
        )
        for sid_, c in rows
        if sid_ is not None
    ]
    if employer_count:
        out.append(FacetCount(value="employer", label="Direct from employer", count=employer_count))
    return sorted(out, key=lambda f: f.count, reverse=True)


def _with_employer_only(query: search.JobQuery) -> search.JobQuery:
    from dataclasses import replace

    return replace(query, employer_only=True, source_keys=[])


def _active_filter_summary(q: search.JobQuery) -> dict:
    summary: dict = {}
    for name in (
        "field_slugs",
        "subfield_slugs",
        "country_codes",
        "workplace_types",
        "job_types",
        "experience_levels",
        "source_keys",
    ):
        val = getattr(q, name)
        if val:
            summary[name] = [getattr(v, "value", v) for v in val]
    for name in (
        "city",
        "salary_min",
        "salary_max",
        "posted_within_days",
        "is_remote",
        "employer_only",
    ):
        val = getattr(q, name)
        if val:
            summary[name] = val
    return summary


def _facet_cache_key(q: search.JobQuery) -> str:
    return repr(_active_filter_summary(q)) + f"|q={q.q}"
