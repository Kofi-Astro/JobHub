"""Employer job-posting schemas.

The posting form captures the SAME structured fields as a scraped job (brief),
but as clean, already-typed input rather than something that needs guessing —
so job_type/experience_level/salary are taken at face value here, unlike the
ingestion pipeline's `normalize.py`, which has to infer them from messy text.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models.enums import (
    ExperienceLevel,
    JobStatus,
    JobType,
    ModerationStatus,
    SalaryPeriod,
    WorkplaceType,
)


class JobPostIn(BaseModel):
    title: str = Field(min_length=2, max_length=500)
    description_html: str = Field(min_length=1)

    # Categorization: the employer selects directly from the live taxonomy —
    # no auto-classification guesswork (brief).
    field_slug: str
    subfield_slug: str

    # Location: structured, not free text — the employer knows exactly where
    # the role is, so there is nothing here to parse or infer.
    workplace_type: WorkplaceType
    city: str | None = Field(default=None, max_length=200)
    region: str | None = Field(default=None, max_length=200)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    country_name: str | None = Field(default=None, max_length=100)
    remote_scope: str | None = Field(default=None, max_length=200)  # "Worldwide", "US only", …

    job_type: JobType
    experience_level: ExperienceLevel = ExperienceLevel.UNKNOWN

    # Salary: an explicit "not disclosed" choice, not an absence the system
    # has to infer (contrast with aggregated jobs, where non-disclosure is the
    # default we detect).
    salary_is_disclosed: bool = False
    salary_min: Decimal | None = Field(default=None, ge=0)
    salary_max: Decimal | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    salary_period: SalaryPeriod | None = None

    # The direct application path — required, one form or another (brief: no
    # gates/middlemen; this IS the application path, not a lead-gen form).
    apply_url: str | None = Field(default=None, max_length=2000)
    apply_email: EmailStr | None = None
    apply_instructions: str | None = Field(default=None, max_length=2000)

    # Nice-to-have (brief): only ever an explicit employer answer, never
    # inferred. A checkbox the employer must affirmatively tick.
    visa_sponsorship: bool = False

    @model_validator(mode="after")
    def _check_consistency(self) -> JobPostIn:
        if not (self.apply_url or self.apply_email or self.apply_instructions):
            raise ValueError("Provide an application URL, email, or instructions.")
        if self.workplace_type != WorkplaceType.REMOTE and not (self.city or self.country_code):
            raise ValueError("On-site/hybrid roles need at least a city or country.")
        if self.salary_is_disclosed and self.salary_min is None and self.salary_max is None:
            raise ValueError("Provide a salary figure, or turn off salary disclosure.")
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salary_min cannot be greater than salary_max.")
        return self


class JobPostUpdateIn(BaseModel):
    """Same shape as `JobPostIn`, everything optional — PATCH semantics."""

    title: str | None = Field(default=None, min_length=2, max_length=500)
    description_html: str | None = Field(default=None, min_length=1)
    field_slug: str | None = None
    subfield_slug: str | None = None
    workplace_type: WorkplaceType | None = None
    city: str | None = None
    region: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    country_name: str | None = None
    remote_scope: str | None = None
    job_type: JobType | None = None
    experience_level: ExperienceLevel | None = None
    salary_is_disclosed: bool | None = None
    salary_min: Decimal | None = Field(default=None, ge=0)
    salary_max: Decimal | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    salary_period: SalaryPeriod | None = None
    apply_url: str | None = None
    apply_email: EmailStr | None = None
    apply_instructions: str | None = None
    visa_sponsorship: bool | None = None


class EmployerJobOut(BaseModel):
    id: uuid.UUID
    title: str
    status: JobStatus
    moderation_status: ModerationStatus
    field_slug: str | None
    subfield_slug: str | None
    location_label: str
    workplace_type: WorkplaceType
    job_type: JobType
    experience_level: ExperienceLevel
    apply_url: str | None
    apply_email: str | None
    view_count: int
    apply_click_count: int
    posted_at: datetime | None
    created_at: datetime


class EmployerStatsOut(BaseModel):
    total_jobs: int
    active_jobs: int
    pending_jobs: int
    total_views: int
    total_apply_clicks: int
