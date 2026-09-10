"""`fields` and `subfields` — the two-level categorization taxonomy.

Field → Sub-field (e.g. "Computing & Tech" → "Web Development"). Both levels are
plain data, fully editable in the admin panel — nothing about a category is
hard-coded in the application.

Aggregated jobs are auto-placed by the keyword classifier, which scores a job's
text against `Subfield.keywords`. Employer jobs are placed by the employer at
submission. An admin can override either, and can remap every job under a
sub-field to another one.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Field(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Top-level category. `slug` is the stable identifier used in URLs and
    filter state; `name` is the display label and can be renamed freely."""

    __tablename__ = "fields"

    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Controls order in the filter sidebar and on the homepage.
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Optional icon name (frontend maps it to an SVG); purely presentational.
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Soft toggle: an inactive field is hidden from filters/homepage but its
    # jobs keep their category (so re-activating is lossless).
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    subfields: Mapped[list[Subfield]] = relationship(
        back_populates="field",
        cascade="all, delete-orphan",
        order_by="Subfield.display_order",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Field {self.slug}>"


class Subfield(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Second-level category, always belonging to exactly one `Field`."""

    __tablename__ = "subfields"
    __table_args__ = (
        # `slug` is unique *within* a field, not globally — "design" can exist
        # under more than one parent if the taxonomy ever needs it.
        UniqueConstraint("field_id", "slug", name="uq_subfields_field_id_slug"),
    )

    field_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("fields.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    field: Mapped[Field] = relationship(back_populates="subfields")

    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Terms the keyword classifier matches against a job's title/description.
    # Admin-editable — when a non-technical admin sees a mis-categorized job,
    # the fix is adding/removing a keyword here, not a code change.
    keywords: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list, server_default="{}"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Subfield {self.slug}>"
