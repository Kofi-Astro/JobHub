"""Job-seeker account schemas: saved jobs, saved searches (incl. alerts), and
the one-time anonymous-state merge on first login."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AlertFrequency
from app.schemas.jobs import JobCard


class SavedJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    notes: str | None
    created_at: datetime
    job: JobCard


class SaveJobIn(BaseModel):
    job_id: uuid.UUID
    notes: str | None = Field(default=None, max_length=2000)


class SavedSearchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    # Same shape as the frontend's URL filter state (see util/url.js) — opaque
    # to the API, interpreted by the search service when the alert runs.
    query_params: dict[str, Any] = Field(default_factory=dict)
    alert_enabled: bool = False
    alert_frequency: AlertFrequency | None = None


class SavedSearchUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    query_params: dict[str, Any] | None = None
    alert_enabled: bool | None = None
    alert_frequency: AlertFrequency | None = None


class SavedSearchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    query_params: dict[str, Any]
    alert_enabled: bool
    alert_frequency: AlertFrequency | None
    last_alerted_at: datetime | None
    created_at: datetime


class MergeAnonIn(BaseModel):
    """What the frontend's `store/state.js#exportForMerge()` sends on first
    login. "Resume where you left off" already works per-browser via
    localStorage regardless of login state, so the only thing that actually
    needs server-side merging is which jobs were saved anonymously."""

    saved_job_ids: list[uuid.UUID] = Field(default_factory=list)


class MergeAnonOut(BaseModel):
    saved_jobs_merged: int
