"""`audit_log` — who changed what, in the admin panel.

Every admin mutation (approve an employer, hide a job, edit the taxonomy, remap
jobs, toggle a source) writes one row here with a before/after snapshot. This is
the accountability trail for a multi-admin setup and the "undo reference" when
someone asks "why did this job disappear?".
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
        Index("ix_audit_log_actor", "actor_user_id"),
        Index("ix_audit_log_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # NULL only for system-generated changes (migrations, worker remaps).
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    action: Mapped[str] = mapped_column(
        String(80), nullable=False
    )  # "job.hide", "employer.approve"
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "job", "source", ...
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # Snapshots of the changed fields only (not the whole row) to keep it small.
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
