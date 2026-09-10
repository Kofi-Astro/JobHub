"""Analytics event recording.

Every meaningful action (a search, a job view, an apply click, a signup, a job
post) drops one row into `analytics_events`. The admin dashboard is aggregates
over that table. Writes are intentionally cheap and best-effort — a failure to
record analytics must never break the user-facing request.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import AnalyticsEvent
from app.models.enums import AnalyticsEventType

log = get_logger(__name__)


def record_event(
    db: Session,
    event_type: AnalyticsEventType,
    *,
    session_id: str | None = None,
    user_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    source_id: uuid.UUID | None = None,
    properties: dict[str, Any] | None = None,
    commit: bool = True,
) -> None:
    """Insert one analytics event. Swallows and logs any error."""
    try:
        db.add(
            AnalyticsEvent(
                event_type=event_type,
                session_id=(session_id or "")[:64] or None,
                user_id=user_id,
                job_id=job_id,
                source_id=source_id,
                properties=properties or {},
            )
        )
        if commit:
            db.commit()
    except Exception as exc:
        log.warning("analytics.record_failed", event=event_type.value, error=repr(exc))
        db.rollback()
