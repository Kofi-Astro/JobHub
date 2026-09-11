"""Admin schemas.

Only the moderation-queue shapes live here for now (employer accounts +
employer job postings) — the rest of the admin surface (taxonomy management,
source registry, users, site content, analytics) is built out in a later
milestone once the core data flows are stable, per the brief's build order.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import EmployerAccountStatus, JobStatus, ModerationStatus


class PendingEmployerOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str | None
    company_id: uuid.UUID
    company_name: str
    job_title: str | None
    account_status: EmployerAccountStatus
    created_at: datetime


class PendingJobOut(BaseModel):
    id: uuid.UUID
    title: str
    company_name: str
    employer_email: str
    status: JobStatus
    moderation_status: ModerationStatus
    created_at: datetime


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
