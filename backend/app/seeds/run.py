"""Idempotent seed loader.

    python -m app.seeds.run              # load taxonomy + sources
    python -m app.seeds.run --taxonomy   # just the taxonomy
    python -m app.seeds.run --sources    # just the source registry

Idempotent by natural key:
    * fields / subfields upserted on `slug` (subfield scoped to its field),
    * sources upserted on `key`.
Re-running after editing a seed file updates the changed rows and inserts new
ones. It does NOT delete rows removed from the seed files — deletion is an
explicit admin action, because a removed sub-field may still have jobs attached.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.db.session import session_scope
from app.logging import configure_logging, get_logger
from app.models import Field, Source, Subfield
from app.seeds.sources_seed import SOURCES
from app.seeds.taxonomy_seed import TAXONOMY

log = get_logger(__name__)


def seed_taxonomy(db) -> tuple[int, int]:
    """Upsert every field and sub-field. Returns (fields_touched, subfields_touched)."""
    fields_touched = 0
    subfields_touched = 0

    for order, sf in enumerate(TAXONOMY):
        field_row = db.scalar(select(Field).where(Field.slug == sf.slug))
        if field_row is None:
            field_row = Field(slug=sf.slug)
            db.add(field_row)
        # Always refresh the descriptive attributes so seed edits propagate.
        field_row.name = sf.name
        field_row.description = sf.description
        field_row.icon = sf.icon
        field_row.display_order = order
        db.flush()  # assign field_row.id for the sub-field FK
        fields_touched += 1

        for sub_order, ssf in enumerate(sf.subfields):
            sub_row = db.scalar(
                select(Subfield).where(Subfield.field_id == field_row.id, Subfield.slug == ssf.slug)
            )
            if sub_row is None:
                sub_row = Subfield(field_id=field_row.id, slug=ssf.slug)
                db.add(sub_row)
            sub_row.name = ssf.name
            sub_row.display_order = sub_order
            # Keywords are fully replaced from the seed — the seed file is the
            # source of truth for the *starting* set; admin edits after that
            # should be made in the admin UI (and, ideally, folded back here).
            sub_row.keywords = list(ssf.keywords)
            subfields_touched += 1

    return fields_touched, subfields_touched


def seed_sources(db) -> int:
    """Upsert every source row. Returns the count touched.

    Operational fields an admin is expected to tune at runtime
    (`enabled`, `rate_limit_per_min`, `config`, `refresh_interval_minutes`) are
    only set when the row is first CREATED, so re-seeding never clobbers an
    admin's live tuning. Identity/wiring fields (adapter, kind, base_url,
    api_key_ref) are always refreshed.
    """
    touched = 0
    for s in SOURCES:
        row = db.scalar(select(Source).where(Source.key == s.key))
        is_new = row is None
        if is_new:
            row = Source(key=s.key)
            db.add(row)

        # Always kept in sync with the seed (code-level wiring):
        row.name = s.name
        row.adapter = s.adapter
        row.kind = s.kind
        row.tier = s.tier
        row.priority = s.priority
        row.requires_api_key = s.requires_api_key
        row.api_key_ref = s.api_key_ref
        row.base_url = s.base_url

        # Only initialised on first insert (admin-owned thereafter):
        if is_new:
            row.enabled = s.enabled
            row.rate_limit_per_min = s.rate_limit_per_min
            row.refresh_interval_minutes = s.refresh_interval_minutes
            row.config = dict(s.config)

        touched += 1
    return touched


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Load JobHub seed data.")
    parser.add_argument("--taxonomy", action="store_true", help="seed taxonomy only")
    parser.add_argument("--sources", action="store_true", help="seed sources only")
    args = parser.parse_args()

    both = not (args.taxonomy or args.sources)

    with session_scope() as db:
        if both or args.taxonomy:
            f, sub = seed_taxonomy(db)
            log.info("seed.taxonomy", fields=f, subfields=sub)
        if both or args.sources:
            n = seed_sources(db)
            log.info("seed.sources", sources=n)

    log.info("seed.done")


if __name__ == "__main__":
    main()
