"""Controlled vocabularies used across the data model.

WHAT: Every fixed-choice column (job type, workplace type, lifecycle status, …)
draws its values from a `StrEnum` here.

WHY `StrEnum` + `native_enum=False`: the values are stored in Postgres as short
`VARCHAR` guarded by a `CHECK` constraint, not as a native `CREATE TYPE` enum.
    * Adding/removing an allowed value later is a one-line constraint swap in a
      migration — no `ALTER TYPE`, no type-dependency juggling. The brief calls
      for a data model that grows "without restructuring", and enum evolution is
      the most common place that promise breaks.
    * Raw SQL and DB tooling show `'full_time'`, not an opaque OID.
    * The Python side still gets a real enum (autocomplete, exhaustiveness).

Taxonomy (field / sub-field) is deliberately NOT here — it is admin-editable data
in tables, not a code-level vocabulary.
"""

from __future__ import annotations

import enum

import sqlalchemy as sa


class SourceKind(enum.StrEnum):
    """Shape of a source, which decides how its adapter behaves and how dedupe
    ranks it (see `Source.priority`)."""

    AGGREGATOR = "aggregator"  # multi-company job board API (Remotive, Adzuna, …)
    ATS = "ats"  # a single company's applicant-tracking board (Greenhouse, Lever)
    SCRAPER = "scraper"  # HTML scrape fallback (ships disabled; API-first policy)


class SourceTier(enum.StrEnum):
    """Free vs paid API plan. This is the "paid tier is a config change" hook —
    flipping it plus adding a key ref is all it takes to promote a source."""

    FREE = "free"
    PAID = "paid"


class SourceRunStatus(enum.StrEnum):
    """Outcome of one ingestion run, shown on the admin sync-health screen."""

    RUNNING = "running"
    SUCCESS = "success"  # completed, safe to expire jobs not seen this run
    PARTIAL = "partial"  # some pages/boards failed; do NOT expire anything
    FAILED = "failed"  # nothing usable ingested


class JobOrigin(enum.StrEnum):
    """The one structural distinction between the two kinds of listing.

    `aggregated` → came from a `Source` adapter.
    `employer`   → posted directly through the employer portal.
    Both live in the same `jobs` table and are searched identically.
    """

    AGGREGATED = "aggregated"
    EMPLOYER = "employer"


class WorkplaceType(enum.StrEnum):
    """Where the work physically happens. `unknown` is a real, kept value — the
    normalizer never guesses this away when a source is silent."""

    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class JobType(enum.StrEnum):
    """Employment arrangement. Brief filter list is full/part/contract/intern;
    `temporary` and `other` are carried so odd source values are not forced into
    a wrong bucket, and `unknown` for silent sources."""

    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"
    TEMPORARY = "temporary"
    OTHER = "other"
    UNKNOWN = "unknown"


class ExperienceLevel(enum.StrEnum):
    """Seniority. Brief lists entry/mid/senior; `lead` is separated because many
    ATS feeds distinguish it and users filter for/against it."""

    ENTRY = "entry"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    UNKNOWN = "unknown"


class SalaryPeriod(enum.StrEnum):
    """Unit the salary figures are quoted in. Needed to compare/convert ranges
    (an hourly 40 and a yearly 80k must not sort together naively)."""

    YEAR = "year"
    MONTH = "month"
    WEEK = "week"
    DAY = "day"
    HOUR = "hour"


class CategorizationMethod(enum.StrEnum):
    """How a job got its field/sub-field — surfaced to admins for triage and
    used to protect human decisions from being overwritten by the classifier."""

    KEYWORD = "keyword"  # automatic keyword scoring (aggregated jobs)
    EMPLOYER = "employer"  # employer picked it at submission
    ADMIN = "admin"  # an admin set/corrected it
    NONE = "none"  # not yet classified / classifier abstained


class JobStatus(enum.StrEnum):
    """Lifecycle of a listing. Orthogonal to `moderation_status` (an employer job
    can be `pending` moderation while its status is also `pending`)."""

    ACTIVE = "active"  # visible in search
    PENDING = "pending"  # employer job awaiting first-time moderation
    REJECTED = "rejected"  # moderation rejected it
    CLOSED = "closed"  # employer closed the role
    EXPIRED = "expired"  # aggregated job fell off its source / past expires_at
    HIDDEN = "hidden"  # an admin manually hid it


class ModerationStatus(enum.StrEnum):
    """Employer-submission review state. `not_required` for aggregated jobs and
    for trusted employers whose first posting was already approved."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class UserRole(enum.StrEnum):
    """Top-level account type. Drives which signup endpoint created the account,
    which dashboard it sees, and every role check on protected routes."""

    SEEKER = "seeker"
    EMPLOYER = "employer"
    ADMIN = "admin"


class EmployerAccountStatus(enum.StrEnum):
    """Moderation state of an employer *account* (distinct from a job posting).
    New accounts start `pending` so spam companies never reach the public site."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class AdminRole(enum.StrEnum):
    """Role-based access for multiple admins. `authz.py` maps each to a set of
    permitted actions; `superadmin` implies all."""

    SUPERADMIN = "superadmin"  # everything, incl. managing other admins
    MODERATOR = "moderator"  # approve/reject employers + postings, hide listings
    EDITOR = "editor"  # taxonomy, sources, site content
    ANALYST = "analyst"  # read-only + analytics


class AlertFrequency(enum.StrEnum):
    """How often a saved-search alert email may fire."""

    DAILY = "daily"
    WEEKLY = "weekly"


class AlertDeliveryStatus(enum.StrEnum):
    SENT = "sent"
    SKIPPED = "skipped"  # nothing new since last run
    FAILED = "failed"


class AnnouncementLevel(enum.StrEnum):
    INFO = "info"
    WARNING = "warning"
    SUCCESS = "success"


class AnalyticsEventType(enum.StrEnum):
    """Append-only event stream feeding the admin analytics dashboard."""

    PAGE_VIEW = "page_view"
    SEARCH = "search"
    JOB_VIEW = "job_view"
    APPLY_CLICK = "apply_click"
    FILTER_APPLY = "filter_apply"
    SEEKER_SIGNUP = "seeker_signup"
    EMPLOYER_SIGNUP = "employer_signup"
    JOB_POST = "job_post"
    SAVED_JOB = "saved_job"
    SAVED_SEARCH = "saved_search"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def pg_enum(enum_cls: type[enum.StrEnum], name: str) -> sa.Enum:
    """Build the SQLAlchemy `Enum` type used by model columns.

    `native_enum=False` → stored as VARCHAR + CHECK (see module docstring).
    `values_callable`    → persist the `.value` string, not the member `.name`.
    `name`               → names the CHECK constraint deterministically so
                           migrations stay stable.
    """
    return sa.Enum(
        enum_cls,
        native_enum=False,
        length=32,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )
