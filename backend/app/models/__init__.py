"""ORM models — the data model of record.

Every model is re-exported here so that:
    * `alembic/env.py` can `import app.models` and see the full `Base.metadata`
      for autogenerate,
    * application code imports from one place (`from app.models import Job`).

Populated in milestone 2.
"""

# Milestone 2 adds, in dependency order:
#   from app.models.source import Source, SourceRun
#   from app.models.taxonomy import Field, Subfield
#   from app.models.company import Company
#   from app.models.user import User, EmployerProfile, AdminProfile, RefreshToken
#   from app.models.job import Job
#   from app.models.saved import SavedJob, SavedSearch, AlertDelivery
#   from app.models.content import SiteContent, Announcement
#   from app.models.analytics import AnalyticsEvent
#   from app.models.audit import AuditLog

__all__: list[str] = []
