"""Company directory resolution.

Ingestion and the employer portal both need "get the `Company` row for this
name, creating it if new". Matching is on `companies.match_key` (normalized name,
see `app/util/text.normalize_company_name`) so "Acme, Inc." and "acme" map to one
row across every source.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company
from app.util.text import normalize_company_name, slugify


def resolve_company(
    db: Session,
    raw_name: str | None,
    *,
    website: str | None = None,
    logo_url: str | None = None,
) -> Company | None:
    """Return the `Company` for `raw_name`, creating it if it does not exist.

    Returns None only when `raw_name` is empty/placeholder — a job with no
    company still stores `company_name_raw` and simply has `company_id = NULL`.
    """
    name = (raw_name or "").strip()
    if not name or name.lower() in {"unknown", "n/a", "confidential", "private"}:
        return None

    match_key = normalize_company_name(name)
    if not match_key:
        return None

    existing = db.scalar(select(Company).where(Company.match_key == match_key))
    if existing is not None:
        # Backfill metadata we did not have before, but never overwrite.
        if website and not existing.website:
            existing.website = website
        if logo_url and not existing.logo_url:
            existing.logo_url = logo_url
        return existing

    company = Company(
        name=name,
        match_key=match_key,
        slug=_unique_slug(db, name),
        website=website,
        logo_url=logo_url,
    )
    db.add(company)
    db.flush()  # assign id for the FK on the job row
    return company


def _unique_slug(db: Session, name: str) -> str:
    """`slugify(name)`, with a numeric suffix if that slug is taken."""
    base = slugify(name)
    candidate = base
    n = 2
    while db.scalar(select(Company.id).where(Company.slug == candidate)) is not None:
        candidate = f"{base}-{n}"
        n += 1
    return candidate
