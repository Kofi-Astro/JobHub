"""Admin schemas for general job management, user management, site content,
announcements, and the analytics summary."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import (
    AdminRole,
    AnnouncementLevel,
    EmployerAccountStatus,
    JobOrigin,
    JobStatus,
    UserRole,
)

# --- Jobs ------------------------------------------------------------------


class AdminJobOut(BaseModel):
    id: uuid.UUID
    title: str
    company_name: str
    origin: JobOrigin
    status: JobStatus
    is_uncategorized: bool
    source_key: str | None
    view_count: int
    apply_click_count: int
    created_at: datetime


class AdminJobUpdateIn(BaseModel):
    """Manual edit of any listing (brief: "manually edit/hide/unpublish any
    listing"). Only the fields an admin plausibly needs to correct by hand —
    a full field-by-field editor is the employer form's job for their own
    postings; this is for admin correction/moderation of ANY job."""

    title: str | None = Field(default=None, min_length=2, max_length=500)
    status: JobStatus | None = None


class CategorizeIn(BaseModel):
    field_slug: str
    subfield_slug: str


# --- Users -----------------------------------------------------------------


class AdminUserOut(BaseModel):
    id: uuid.UUID
    email: str
    role: UserRole
    full_name: str | None
    is_active: bool
    employer_account_status: EmployerAccountStatus | None = None
    created_at: datetime
    last_login_at: datetime | None


class ResetPasswordOut(BaseModel):
    temporary_password: str


# --- Admins (superadmin only) ---------------------------------------------


class AdminCreateIn(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=200)
    full_name: str | None = None
    admin_role: AdminRole = AdminRole.MODERATOR


class AdminOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    admin_role: AdminRole
    is_active: bool


# --- Site content ------------------------------------------------------------


class SiteContentOut(BaseModel):
    key: str
    value: Any
    updated_at: datetime


class SiteContentSetIn(BaseModel):
    value: Any


class AnnouncementIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    level: AnnouncementLevel = AnnouncementLevel.INFO
    is_active: bool = False
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class AnnouncementOut(AnnouncementIn):
    id: uuid.UUID
    created_at: datetime


# --- Analytics --------------------------------------------------------------


class AnalyticsSummaryOut(BaseModel):
    period_days: int
    page_views: int
    searches: int
    job_views: int
    apply_clicks: int
    top_searches: list[dict[str, Any]]
    jobs_per_source: list[dict[str, Any]]
    seeker_signups: int
    employer_signups: int
    jobs_posted_by_employers: int
