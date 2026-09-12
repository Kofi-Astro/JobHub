"""ORM models — the data model of record.

Every model is imported here so that:
    * `alembic/env.py` sees the full `Base.metadata` for autogenerate,
    * application code imports from one place (`from app.models import Job`),
    * SQLAlchemy resolves string-based relationships (e.g. `relationship("Job")`)
      because every class is registered by the time this module finishes.

Import order follows FK dependencies (referenced tables first).
"""

from app.models.analytics import AnalyticsEvent
from app.models.audit import AuditLog
from app.models.company import Company
from app.models.content import Announcement, SiteContent
from app.models.enums import (  # noqa: F401  (re-exported for convenience)
    AdminRole,
    AlertDeliveryStatus,
    AlertFrequency,
    AnalyticsEventType,
    AnnouncementLevel,
    CategorizationMethod,
    EmployerAccountStatus,
    ExperienceLevel,
    JobOrigin,
    JobStatus,
    JobType,
    ModerationStatus,
    SalaryPeriod,
    SourceKind,
    SourceRunStatus,
    SourceTier,
    UserRole,
    WorkplaceType,
)
from app.models.job import Job
from app.models.saved import AlertDelivery, SavedJob, SavedSearch
from app.models.source import Source, SourceRun
from app.models.taxonomy import Field, Subfield
from app.models.user import AdminProfile, EmployerProfile, RefreshToken, User

__all__ = [
    "AdminProfile",
    "AlertDelivery",
    "AnalyticsEvent",
    "Announcement",
    "AuditLog",
    "Company",
    "EmployerProfile",
    "Field",
    "Job",
    "RefreshToken",
    "SavedJob",
    "SavedSearch",
    "SiteContent",
    "Source",
    "SourceRun",
    "Subfield",
    "User",
]
