"""Admin schemas for taxonomy and source-registry management."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import SourceKind, SourceRunStatus, SourceTier

# --- Taxonomy ----------------------------------------------------------


class SubfieldAdminOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    display_order: int
    is_active: bool
    keywords: list[str]
    job_count: int = 0


class FieldAdminOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    icon: str | None
    display_order: int
    is_active: bool
    subfields: list[SubfieldAdminOut]


class FieldCreateIn(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    icon: str | None = None
    display_order: int = 0


class FieldUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    icon: str | None = None
    display_order: int | None = None
    is_active: bool | None = None


class SubfieldCreateIn(BaseModel):
    field_id: uuid.UUID
    slug: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    display_order: int = 0
    keywords: list[str] = Field(default_factory=list)


class SubfieldUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    display_order: int | None = None
    is_active: bool | None = None
    keywords: list[str] | None = None


class RemapIn(BaseModel):
    target_subfield_id: uuid.UUID


class UncategorizedJobOut(BaseModel):
    id: uuid.UUID
    title: str
    company_name: str
    origin: str
    created_at: datetime


# --- Sources -------------------------------------------------------------


class SourceAdminOut(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    adapter: str
    kind: SourceKind
    enabled: bool
    tier: SourceTier
    base_url: str | None
    config: dict[str, Any]
    requires_api_key: bool
    api_key_ref: str | None
    rate_limit_per_min: int | None
    refresh_interval_minutes: int
    priority: int
    last_run_at: datetime | None
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None
    consecutive_failures: int
    job_count: int = 0


class SourceCreateIn(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    adapter: str = Field(min_length=1, max_length=64)
    kind: SourceKind
    tier: SourceTier = SourceTier.FREE
    base_url: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    requires_api_key: bool = False
    api_key_ref: str | None = None
    rate_limit_per_min: int | None = None
    refresh_interval_minutes: int = 360
    priority: int = 10


class SourceUpdateIn(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    tier: SourceTier | None = None
    base_url: str | None = None
    config: dict[str, Any] | None = None
    requires_api_key: bool | None = None
    api_key_ref: str | None = None
    rate_limit_per_min: int | None = None
    refresh_interval_minutes: int | None = None
    priority: int | None = None


class SourceRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    started_at: datetime
    finished_at: datetime | None
    status: SourceRunStatus
    jobs_seen: int
    jobs_created: int
    jobs_updated: int
    jobs_expired: int
    jobs_failed: int
    error: str | None
