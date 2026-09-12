"""Admin: source registry management (brief: "add/edit/disable, tier/free-vs-
paid, API keys, rate limits, sync health/error logs").

This is the concrete form of "upgrading a source is a config change, not a
rewrite" — every field an operator tunes lives on the row, editable here with
no deploy. `api_key_ref` only ever stores the NAME of an environment variable
(never a raw secret); resolving it happens at request time in
`Settings.resolve_api_key`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_admin_permission
from app.config import get_settings
from app.db import get_db
from app.ingestion.pipeline import run_source
from app.models import Job, Source, SourceRun, User
from app.schemas.admin_catalog import (
    SourceAdminOut,
    SourceCreateIn,
    SourceRunOut,
    SourceUpdateIn,
)
from app.services.audit import log_action

router = APIRouter(prefix="/api/admin/sources", tags=["admin-sources"])

_manage = require_admin_permission("sources.manage")


def _to_out(source: Source, job_count: int) -> SourceAdminOut:
    return SourceAdminOut(
        id=source.id,
        key=source.key,
        name=source.name,
        adapter=source.adapter,
        kind=source.kind,
        enabled=source.enabled,
        tier=source.tier,
        base_url=source.base_url,
        config=source.config,
        requires_api_key=source.requires_api_key,
        api_key_ref=source.api_key_ref,
        rate_limit_per_min=source.rate_limit_per_min,
        refresh_interval_minutes=source.refresh_interval_minutes,
        priority=source.priority,
        last_run_at=source.last_run_at,
        last_success_at=source.last_success_at,
        last_error_at=source.last_error_at,
        last_error=source.last_error,
        consecutive_failures=source.consecutive_failures,
        job_count=job_count,
    )


@router.get("", response_model=list[SourceAdminOut])
def list_sources(
    admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> list[SourceAdminOut]:
    counts = dict(db.execute(select(Job.source_id, func.count()).group_by(Job.source_id)).all())
    sources = db.scalars(select(Source).order_by(Source.name)).all()
    return [_to_out(s, counts.get(s.id, 0)) for s in sources]


@router.post("", response_model=SourceAdminOut, status_code=201)
def create_source(
    body: SourceCreateIn, admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> SourceAdminOut:
    source = Source(**body.model_dump(), enabled=False)  # never auto-enable a brand-new source
    db.add(source)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail=f"Source key {body.key!r} already exists."
        ) from exc
    log_action(
        db, admin.id, "source.create", "source", source.id, after=body.model_dump(mode="json")
    )
    db.commit()
    return _to_out(source, 0)


def _source_or_404(db: Session, source_id: uuid.UUID) -> Source:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    return source


@router.patch("/{source_id}", response_model=SourceAdminOut)
def update_source(
    source_id: uuid.UUID,
    body: SourceUpdateIn,
    admin: User = Depends(_manage),
    db: Session = Depends(get_db),
) -> SourceAdminOut:
    source = _source_or_404(db, source_id)
    updates = body.model_dump(exclude_unset=True)
    if updates.get("enabled") and source.requires_api_key:
        # `api_key_ref` merely NAMES the environment variable (seeded up front
        # for every keyed source, per ARCHITECTURE.md) — enabling requires that
        # variable to actually hold a value, not just that the row points at one.
        ref = updates.get("api_key_ref", source.api_key_ref)
        if not ref or not get_settings().resolve_api_key(ref):
            raise HTTPException(
                status_code=422,
                detail=f"No value set for the {ref or 'required'} credential — add it before enabling this source.",
            )

    before = {k: getattr(source, k) for k in updates}
    for attr, value in updates.items():
        setattr(source, attr, value)
    log_action(
        db,
        admin.id,
        "source.update",
        "source",
        source.id,
        before=_jsonable(before),
        after=_jsonable(updates),
    )
    db.commit()
    job_count = (
        db.scalar(select(func.count()).select_from(Job).where(Job.source_id == source.id)) or 0
    )
    return _to_out(source, job_count)


@router.get("/{source_id}/runs", response_model=list[SourceRunOut])
def source_runs(
    source_id: uuid.UUID, admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> list[SourceRunOut]:
    _source_or_404(db, source_id)
    rows = db.scalars(
        select(SourceRun)
        .where(SourceRun.source_id == source_id)
        .order_by(SourceRun.started_at.desc())
        .limit(50)
    ).all()
    return [SourceRunOut.model_validate(r) for r in rows]


@router.post("/{source_id}/run-now", response_model=SourceRunOut)
def run_now(
    source_id: uuid.UUID, admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> SourceRunOut:
    """Trigger an immediate ingestion run, synchronously — an admin action, so
    waiting a few seconds (or longer, for a many-board ATS source) is
    acceptable; the worker's own 5-minute dispatch tick handles the routine
    schedule. Skips it entirely if a run is already in flight."""
    source = _source_or_404(db, source_id)
    if not source.enabled:
        raise HTTPException(status_code=409, detail="Enable the source before running it.")

    from app.worker.tasks import (
        is_run_in_progress,  # local import: worker depends on pipeline, not the reverse
    )

    if is_run_in_progress(db, source):
        raise HTTPException(status_code=409, detail="A run for this source is already in progress.")

    run = run_source(db, source)
    log_action(
        db,
        admin.id,
        "source.run_now",
        "source",
        source.id,
        after={"run_id": str(run.id), "status": run.status.value},
    )
    db.commit()
    return SourceRunOut.model_validate(run)


def _jsonable(d: dict) -> dict:
    """Best-effort JSON-safe copy for `audit_log` (enum members -> their value)."""
    out = {}
    for k, v in d.items():
        out[k] = v.value if hasattr(v, "value") else v
    return out
