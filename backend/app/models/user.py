"""Accounts: `users` + role satellites (`employer_profiles`, `admin_profiles`)
+ `refresh_tokens`.

DESIGN — one `users` table, `role` discriminator, role-specific data in
satellite tables:
    * Authentication (password hashing, login, token issue/rotate) is identical
      for every role. Duplicating it across `seekers` / `employers` tables would
      invite drift and bugs.
    * The "clear separation" the brief asks for is enforced where it matters:
      distinct signup endpoints, distinct dashboards, and a role check on every
      protected route — plus the fact that employer/admin data physically lives
      in a different table that a seeker row simply doesn't have.

Job seekers may have NO account at all — browsing/search/filter/apply all work
anonymously. An account only unlocks saved jobs, saved searches, and alerts.
Employers MUST have an (approved) account to post.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    AdminRole,
    EmployerAccountStatus,
    UserRole,
    pg_enum,
)


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role"), nullable=False, index=True
    )

    # `citext` (case-insensitive text) so "Ada@x.com" and "ada@x.com" collide on
    # the unique index. The `citext` extension is created in the first migration.
    email: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False)

    # Nullable to leave room for future OAuth-only accounts. A NULL hash means
    # password login is disabled for that user.
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)

    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Satellite rows (exactly one is present, matching `role`; seekers have none).
    # `foreign_keys` is explicit because EmployerProfile has TWO FKs to users
    # (`user_id` and `approved_by_id`); this relationship follows `user_id`.
    employer_profile: Mapped[EmployerProfile | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
        foreign_keys="EmployerProfile.user_id",
    )
    admin_profile: Mapped[AdminProfile | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.email} role={self.role}>"


class EmployerProfile(TimestampMixin, Base):
    """1:1 with a `role=employer` user. Holds the company link, the account
    moderation state, and the **monetization hooks** (all nullable / permissive
    in v1 so posting is free, but present so paid tiers are a later feature
    flip rather than a migration)."""

    __tablename__ = "employer_profiles"

    # PK == FK: enforces the 1:1 and makes the row addressable by user id.
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user: Mapped[User] = relationship(back_populates="employer_profile", foreign_keys=[user_id])

    company_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # --- Account moderation ------------------------------------------------
    account_status: Mapped[EmployerAccountStatus] = mapped_column(
        pg_enum(EmployerAccountStatus, "employer_account_status"),
        nullable=False,
        default=EmployerAccountStatus.PENDING,
        index=True,
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Monetization hooks (v1: NULL everywhere == free + unlimited) --------
    # `plan` NULL = free tier. A value ("standard", "featured", …) is a later
    # feature; the column existing now means no schema change to introduce it.
    plan: Mapped[str | None] = mapped_column(String(50), nullable=True)
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # NULL = unlimited active postings. The employer job-create endpoint checks
    # this against a live count; enforcing a quota later is just seeding a number.
    posting_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EmployerProfile user={self.user_id} status={self.account_status}>"


class AdminProfile(TimestampMixin, Base):
    """1:1 with a `role=admin` user. `admin_role` is resolved to a set of
    permitted actions in `app/services/authz.py` (role-based access for
    multiple admins)."""

    __tablename__ = "admin_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user: Mapped[User] = relationship(back_populates="admin_profile")

    admin_role: Mapped[AdminRole] = mapped_column(
        pg_enum(AdminRole, "admin_role"), nullable=False, default=AdminRole.MODERATOR
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AdminProfile user={self.user_id} role={self.admin_role}>"


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single issued refresh token, stored **hashed**.

    WHY store them: the API uses short-lived access tokens (~15 min) plus a
    long-lived rotating refresh token. Persisting the hash lets us (a) rotate on
    each use, (b) revoke a stolen token or "log out everywhere", and (c) cap the
    number of live sessions per user. The raw token never touches the DB.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user: Mapped[User] = relationship(back_populates="refresh_tokens")

    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set when rotated or explicitly revoked; a non-null value = unusable.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Captured for the "active sessions" screen and abuse investigation.
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RefreshToken user={self.user_id} revoked={self.revoked_at is not None}>"
