"""`companies` — a light directory of hiring organizations.

Two ways a company row appears:
    * Aggregated ingestion resolves the raw company name to a row
      (create-if-missing, matched on a normalized name key).
    * An employer registers; their `EmployerProfile` links to a company row,
      and `is_verified` is set once an admin approves the account.

Kept intentionally thin — this is not a CRM. Everything a job card needs
(name, logo) is here; anything richer can be added later without touching `jobs`.
"""

from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Company(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    # Normalized name (lowercased, punctuation/suffix-stripped) used to match
    # "Acme, Inc." and "acme inc" to the same row during ingestion. Indexed and
    # unique so the resolver is a single upsert.
    match_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # True once an employer has claimed this company and an admin approved it.
    # Drives the "Direct from employer" trust signal only — never search ranking.
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Company {self.slug}>"
