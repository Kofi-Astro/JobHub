"""Public taxonomy endpoint: the field → sub-field tree.

Consumed by the filter sidebar and the employer posting form. Cached in-process
for a minute — the taxonomy changes rarely (admin edits) and this is hit on
every page load.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Field
from app.schemas.taxonomy import FieldOut, TaxonomyTree

router = APIRouter(prefix="/api/taxonomy", tags=["taxonomy"])

_CACHE_TTL = 60.0
_cache: dict[str, tuple[float, TaxonomyTree]] = {}


@router.get("", response_model=TaxonomyTree, summary="Field / sub-field tree")
def get_taxonomy(db: Session = Depends(get_db)) -> TaxonomyTree:
    hit = _cache.get("tree")
    if hit and (time.monotonic() - hit[0]) < _CACHE_TTL:
        return hit[1]

    fields = db.scalars(
        select(Field)
        .where(Field.is_active.is_(True))
        .order_by(Field.display_order, Field.name)
        .options(selectinload(Field.subfields))
    ).all()

    tree = TaxonomyTree(
        fields=[
            FieldOut(
                id=f.id,
                slug=f.slug,
                name=f.name,
                description=f.description,
                icon=f.icon,
                display_order=f.display_order,
                subfields=[
                    s
                    for s in sorted(f.subfields, key=lambda s: (s.display_order, s.name))
                    if s.is_active
                ],
            )
            for f in fields
        ]
    )
    _cache["tree"] = (time.monotonic(), tree)
    return tree
