"""Admin: site content management (brief: "homepage featured categories,
banners/announcements") — and the one PUBLIC endpoint that reads the active
announcement, which belongs here since it serves the same data these routes
manage.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin_permission
from app.db import get_db
from app.models import Announcement, SiteContent, User
from app.schemas.admin_ops import (
    AnnouncementIn,
    AnnouncementOut,
    SiteContentOut,
    SiteContentSetIn,
)
from app.schemas.common import Message
from app.services.audit import log_action

_manage = require_admin_permission("content.manage")


# --- Site content (arbitrary key -> JSON blob; see model docstring for the
# documented key namespace, e.g. "homepage.hero", "homepage.featured_fields")

admin_content_router = APIRouter(prefix="/api/admin/content", tags=["admin-content"])


@admin_content_router.get("", response_model=list[SiteContentOut])
def list_content(
    admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> list[SiteContentOut]:
    rows = db.scalars(select(SiteContent).order_by(SiteContent.key)).all()
    return [SiteContentOut(key=r.key, value=r.value, updated_at=r.updated_at) for r in rows]


@admin_content_router.put("/{key}", response_model=SiteContentOut)
def set_content(
    key: str, body: SiteContentSetIn, admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> SiteContentOut:
    row = db.scalar(select(SiteContent).where(SiteContent.key == key))
    before = row.value if row else None
    if row is None:
        row = SiteContent(key=key, value=body.value, updated_by_id=admin.id)
        db.add(row)
    else:
        row.value = body.value
        row.updated_by_id = admin.id
    log_action(
        db,
        admin.id,
        "content.set",
        "site_content",
        None,
        before={"value": before},
        after={"key": key, "value": body.value},
    )
    db.commit()
    return SiteContentOut(key=row.key, value=row.value, updated_at=row.updated_at)


# --- Announcements -----------------------------------------------------------

admin_announcements_router = APIRouter(prefix="/api/admin/announcements", tags=["admin-content"])


def _to_out(a: Announcement) -> AnnouncementOut:
    return AnnouncementOut(
        id=a.id,
        title=a.title,
        body=a.body,
        level=a.level,
        is_active=a.is_active,
        starts_at=a.starts_at,
        ends_at=a.ends_at,
        created_at=a.created_at,
    )


@admin_announcements_router.get("", response_model=list[AnnouncementOut])
def list_announcements(
    admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> list[AnnouncementOut]:
    rows = db.scalars(select(Announcement).order_by(Announcement.created_at.desc())).all()
    return [_to_out(a) for a in rows]


@admin_announcements_router.post("", response_model=AnnouncementOut, status_code=201)
def create_announcement(
    body: AnnouncementIn, admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> AnnouncementOut:
    row = Announcement(**body.model_dump(), created_by_id=admin.id)
    db.add(row)
    log_action(
        db,
        admin.id,
        "announcement.create",
        "announcement",
        None,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return _to_out(row)


@admin_announcements_router.patch("/{announcement_id}", response_model=AnnouncementOut)
def update_announcement(
    announcement_id: uuid.UUID,
    body: AnnouncementIn,
    admin: User = Depends(_manage),
    db: Session = Depends(get_db),
) -> AnnouncementOut:
    row = db.get(Announcement, announcement_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Announcement not found.")
    for attr, value in body.model_dump().items():
        setattr(row, attr, value)
    log_action(
        db,
        admin.id,
        "announcement.update",
        "announcement",
        row.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return _to_out(row)


@admin_announcements_router.delete("/{announcement_id}", response_model=Message)
def delete_announcement(
    announcement_id: uuid.UUID, admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> Message:
    row = db.get(Announcement, announcement_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Announcement not found.")
    db.delete(row)
    log_action(db, admin.id, "announcement.delete", "announcement", announcement_id)
    db.commit()
    return Message(detail="Announcement deleted.")


# --- Public read (used by the frontend banner + homepage) -----------------

public_router = APIRouter(prefix="/api", tags=["meta"])


@public_router.get("/announcements/active", response_model=AnnouncementOut | None)
def active_announcement(db: Session = Depends(get_db)) -> AnnouncementOut | None:
    now = datetime.now(UTC)
    row = db.scalar(
        select(Announcement)
        .where(
            Announcement.is_active.is_(True),
            (Announcement.starts_at.is_(None)) | (Announcement.starts_at <= now),
            (Announcement.ends_at.is_(None)) | (Announcement.ends_at >= now),
        )
        .order_by(Announcement.created_at.desc())
    )
    return _to_out(row) if row else None


@public_router.get("/content/{key}", response_model=SiteContentOut | None)
def get_public_content(key: str, db: Session = Depends(get_db)) -> SiteContentOut | None:
    """Public read of one content key (e.g. `homepage.featured_fields`) — the
    homepage fetches whichever keys it renders; anything not set is just None,
    so the frontend can fall back to a sane default."""
    row = db.scalar(select(SiteContent).where(SiteContent.key == key))
    return SiteContentOut(key=row.key, value=row.value, updated_at=row.updated_at) if row else None
