"""Job response models.

`JobCard` is the compact shape for search results; `JobDetail` adds the full
description, application path, and provenance. Both are built from a `Job` ORM
row plus its eager-loaded `company` / `source`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models import Job
from app.models.enums import (
    ExperienceLevel,
    JobOrigin,
    JobType,
    SalaryPeriod,
    WorkplaceType,
)

# Label shown wherever a source is named for an employer-posted job.
DIRECT_FROM_EMPLOYER = "Direct from employer"


class SalaryOut(BaseModel):
    """Present only when disclosed; the frontend shows "Not disclosed" when null."""

    min: Decimal | None
    max: Decimal | None
    currency: str | None
    period: SalaryPeriod | None


class JobCard(BaseModel):
    id: uuid.UUID
    title: str
    company_name: str
    company_slug: str | None
    company_logo_url: str | None

    location_label: str  # pre-composed "Berlin, Germany" / "Remote" / "Remote (US)"
    country_code: str | None
    workplace_type: WorkplaceType
    is_remote: bool

    salary: SalaryOut | None
    job_type: JobType
    experience_level: ExperienceLevel

    field_slug: str | None
    subfield_slug: str | None

    source_label: str  # aggregated source name, or "Direct from employer"
    is_direct_from_employer: bool

    posted_at: datetime | None

    @classmethod
    def from_job(cls, job: Job) -> JobCard:
        return cls(
            id=job.id,
            title=job.title,
            company_name=job.company.name if job.company else job.company_name_raw,
            company_slug=job.company.slug if job.company else None,
            company_logo_url=job.company.logo_url if job.company else None,
            location_label=_location_label(job),
            country_code=job.country_code,
            workplace_type=job.workplace_type,
            is_remote=job.is_remote,
            salary=_salary_out(job),
            job_type=job.job_type,
            experience_level=job.experience_level,
            field_slug=job.field.slug if job.field else None,
            subfield_slug=job.subfield.slug if job.subfield else None,
            source_label=(
                DIRECT_FROM_EMPLOYER
                if job.origin == JobOrigin.EMPLOYER
                else (job.source.name if job.source else "Aggregated")
            ),
            is_direct_from_employer=job.origin == JobOrigin.EMPLOYER,
            posted_at=job.posted_at,
        )


class ShadowListing(BaseModel):
    """A non-canonical row for the same role, for "also listed on"."""

    source_label: str
    source_url: str | None


class JobDetail(JobCard):
    description_html: str
    apply_url: str | None
    apply_email: str | None
    apply_instructions: str | None
    source_url: str | None
    remote_scope: str | None
    region: str | None
    city: str | None
    visa_sponsorship: bool | None
    ingested_at: datetime | None
    also_listed_on: list[ShadowListing] = []

    @classmethod
    def from_job(cls, job: Job, *, shadows: list[Job] | None = None) -> JobDetail:
        base = JobCard.from_job(job).model_dump()
        return cls(
            **base,
            description_html=job.description_html,
            apply_url=job.apply_url,
            apply_email=job.apply_email,
            apply_instructions=job.apply_instructions,
            source_url=job.source_url,
            remote_scope=job.remote_scope,
            region=job.region,
            city=job.city,
            visa_sponsorship=job.visa_sponsorship,
            ingested_at=job.ingested_at,
            also_listed_on=[
                ShadowListing(
                    source_label=(s.source.name if s.source else DIRECT_FROM_EMPLOYER),
                    source_url=s.source_url,
                )
                for s in (shadows or [])
            ],
        )


class ApplyTarget(BaseModel):
    """Returned by the apply-click endpoint so the frontend can navigate out."""

    url: str | None
    email: str | None
    instructions: str | None


# --- Facets -----------------------------------------------------------------


class FacetCount(BaseModel):
    value: str
    label: str
    count: int


class JobFacets(BaseModel):
    total: int
    fields: list[FacetCount]
    subfields: list[FacetCount]
    workplace_types: list[FacetCount]
    job_types: list[FacetCount]
    experience_levels: list[FacetCount]
    countries: list[FacetCount]
    sources: list[FacetCount]


# --- helpers ---------------------------------------------------------------


def _salary_out(job: Job) -> SalaryOut | None:
    if not job.salary_is_disclosed:
        return None
    return SalaryOut(
        min=job.salary_min,
        max=job.salary_max,
        currency=job.salary_currency,
        period=job.salary_period,
    )


def _location_label(job: Job) -> str:
    if job.is_remote:
        return f"Remote ({job.remote_scope})" if job.remote_scope else "Remote"
    parts = [p for p in (job.city, job.region, job.country_name) if p]
    return ", ".join(dict.fromkeys(parts)) or (job.location_raw or "—")
