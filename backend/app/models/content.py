"""Admin-managed site content: `site_content` and `announcements`.

Keeps the homepage and site banners editable from the admin panel without a
deploy (brief: "Site content management — homepage featured categories,
banners/announcements").
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AnnouncementLevel, pg_enum


class SiteContent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single key→JSON blob of editable content.

    Known keys (documented, not enforced — new keys need no migration):
        homepage.hero            {headline, subhead, cta_label}
        homepage.featured_fields [field_slug, ...]      shown as homepage tiles
        homepage.stats_enabled   bool
        footer.links             [{label, href}, ...]
    """

    __tablename__ = "site_content"

    key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    value: Mapped[dict[str, Any] | list[Any]] = mapped_column(JSONB, nullable=False)

    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class Announcement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A site-wide banner. `is_active` plus the optional `starts_at`/`ends_at`
    window decide whether it currently shows; the frontend fetches the active
    one on load."""

    __tablename__ = "announcements"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[AnnouncementLevel] = mapped_column(
        pg_enum(AnnouncementLevel, "announcement_level"),
        nullable=False,
        default=AnnouncementLevel.INFO,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
