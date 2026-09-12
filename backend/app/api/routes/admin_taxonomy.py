"""Admin: taxonomy management (brief: "add/edit/remove fields and sub-fields,
re-map miscategorized jobs") and the uncategorized-jobs review queue.

Deleting a field/subfield that still has jobs attached is refused with a plain
4xx explaining why, not left to surface as a raw FK error — the field→subfield
FK already RESTRICTs at the database level, but subfield→job is a soft
reference (`ON DELETE SET NULL`) specifically so this layer can give a better
error than "your jobs silently lost their category".
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Pagination, pagination, require_admin_permission
from app.db import get_db
from app.models import Field, Job, Subfield, User
from app.models.enums import CategorizationMethod
from app.schemas.admin_catalog import (
    FieldAdminOut,
    FieldCreateIn,
    FieldUpdateIn,
    RemapIn,
    SubfieldAdminOut,
    SubfieldCreateIn,
    SubfieldUpdateIn,
    UncategorizedJobOut,
)
from app.schemas.common import Message, Page
from app.services.audit import log_action

router = APIRouter(prefix="/api/admin/taxonomy", tags=["admin-taxonomy"])

_manage = require_admin_permission("taxonomy.manage")


def _job_counts_by_subfield(db: Session) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(Job.subfield_id, func.count())
        .where(Job.subfield_id.isnot(None))
        .group_by(Job.subfield_id)
    ).all()
    return dict(rows)


@router.get("", response_model=list[FieldAdminOut])
def list_taxonomy(
    admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> list[FieldAdminOut]:
    """Every field + sub-field, including inactive ones (unlike the public
    `/api/taxonomy`, which only shows active — an admin needs to see and
    reactivate something they turned off)."""
    counts = _job_counts_by_subfield(db)
    fields = db.scalars(select(Field).order_by(Field.display_order, Field.name)).all()
    return [
        FieldAdminOut(
            id=f.id,
            slug=f.slug,
            name=f.name,
            description=f.description,
            icon=f.icon,
            display_order=f.display_order,
            is_active=f.is_active,
            subfields=[
                SubfieldAdminOut(
                    id=sf.id,
                    slug=sf.slug,
                    name=sf.name,
                    display_order=sf.display_order,
                    is_active=sf.is_active,
                    keywords=sf.keywords,
                    job_count=counts.get(sf.id, 0),
                )
                for sf in sorted(f.subfields, key=lambda s: (s.display_order, s.name))
            ],
        )
        for f in fields
    ]


@router.post("/fields", response_model=FieldAdminOut, status_code=201)
def create_field(
    body: FieldCreateIn, admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> FieldAdminOut:
    field = Field(**body.model_dump())
    db.add(field)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail=f"Field slug {body.slug!r} is already in use."
        ) from exc
    log_action(
        db, admin.id, "taxonomy.field.create", "field", field.id, after=body.model_dump(mode="json")
    )
    db.commit()
    return FieldAdminOut(
        id=field.id,
        slug=field.slug,
        name=field.name,
        description=field.description,
        icon=field.icon,
        display_order=field.display_order,
        is_active=field.is_active,
        subfields=[],  # freshly created: no sub-fields yet
    )


@router.patch("/fields/{field_id}", response_model=Message)
def update_field(
    field_id: uuid.UUID,
    body: FieldUpdateIn,
    admin: User = Depends(_manage),
    db: Session = Depends(get_db),
) -> Message:
    field = db.get(Field, field_id)
    if field is None:
        raise HTTPException(status_code=404, detail="Field not found.")
    before = {"name": field.name, "is_active": field.is_active}
    for attr, value in body.model_dump(exclude_unset=True).items():
        setattr(field, attr, value)
    log_action(
        db,
        admin.id,
        "taxonomy.field.update",
        "field",
        field.id,
        before=before,
        after=body.model_dump(exclude_unset=True, mode="json"),
    )
    db.commit()
    return Message(detail="Field updated.")


@router.delete("/fields/{field_id}", response_model=Message)
def delete_field(
    field_id: uuid.UUID, admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> Message:
    field = db.get(Field, field_id)
    if field is None:
        raise HTTPException(status_code=404, detail="Field not found.")
    if field.subfields:
        raise HTTPException(
            status_code=409,
            detail=f"Delete or move the {len(field.subfields)} sub-field(s) under this field first.",
        )
    db.delete(field)
    log_action(db, admin.id, "taxonomy.field.delete", "field", field_id)
    db.commit()
    return Message(detail="Field deleted.")


@router.post("/subfields", response_model=SubfieldAdminOut, status_code=201)
def create_subfield(
    body: SubfieldCreateIn, admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> SubfieldAdminOut:
    if db.get(Field, body.field_id) is None:
        raise HTTPException(status_code=404, detail="Parent field not found.")
    subfield = Subfield(**body.model_dump())
    db.add(subfield)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail=f"Sub-field slug {body.slug!r} already exists under this field."
        ) from exc
    log_action(
        db,
        admin.id,
        "taxonomy.subfield.create",
        "subfield",
        subfield.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return SubfieldAdminOut(
        id=subfield.id,
        slug=subfield.slug,
        name=subfield.name,
        display_order=subfield.display_order,
        is_active=subfield.is_active,
        keywords=subfield.keywords,
        job_count=0,
    )


@router.patch("/subfields/{subfield_id}", response_model=Message)
def update_subfield(
    subfield_id: uuid.UUID,
    body: SubfieldUpdateIn,
    admin: User = Depends(_manage),
    db: Session = Depends(get_db),
) -> Message:
    subfield = db.get(Subfield, subfield_id)
    if subfield is None:
        raise HTTPException(status_code=404, detail="Sub-field not found.")
    before = {"name": subfield.name, "keywords": subfield.keywords}
    for attr, value in body.model_dump(exclude_unset=True).items():
        setattr(subfield, attr, value)
    log_action(
        db,
        admin.id,
        "taxonomy.subfield.update",
        "subfield",
        subfield.id,
        before=before,
        after=body.model_dump(exclude_unset=True, mode="json"),
    )
    db.commit()
    return Message(
        detail="Sub-field updated. Keyword changes apply to future ingestion; use recategorize to apply retroactively."
    )


@router.post("/subfields/{subfield_id}/remap", response_model=Message)
def remap_subfield(
    subfield_id: uuid.UUID,
    body: RemapIn,
    admin: User = Depends(_manage),
    db: Session = Depends(get_db),
) -> Message:
    """Reassign every job under `subfield_id` to `target_subfield_id`, so the
    source sub-field can then be safely deleted (or simply merged away)."""
    source = db.get(Subfield, subfield_id)
    target = db.get(Subfield, body.target_subfield_id)
    if source is None or target is None:
        raise HTTPException(status_code=404, detail="Sub-field not found.")
    if source.id == target.id:
        raise HTTPException(status_code=422, detail="Source and target sub-field must differ.")

    moved = db.execute(
        Job.__table__.update()
        .where(Job.subfield_id == source.id)
        .values(
            field_id=target.field_id,
            subfield_id=target.id,
            categorization_method=CategorizationMethod.ADMIN,
            is_uncategorized=False,
        )
    )
    log_action(
        db,
        admin.id,
        "taxonomy.subfield.remap",
        "subfield",
        source.id,
        after={"target_subfield_id": str(target.id), "jobs_moved": moved.rowcount},
    )
    db.commit()
    return Message(detail=f"Moved {moved.rowcount} job(s) to {target.name!r}.")


@router.delete("/subfields/{subfield_id}", response_model=Message)
def delete_subfield(
    subfield_id: uuid.UUID, admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> Message:
    subfield = db.get(Subfield, subfield_id)
    if subfield is None:
        raise HTTPException(status_code=404, detail="Sub-field not found.")
    count = db.scalar(select(func.count()).select_from(Job).where(Job.subfield_id == subfield_id))
    if count:
        raise HTTPException(
            status_code=409, detail=f"{count} job(s) use this sub-field — remap them first."
        )
    db.delete(subfield)
    log_action(db, admin.id, "taxonomy.subfield.delete", "subfield", subfield_id)
    db.commit()
    return Message(detail="Sub-field deleted.")


@router.get("/uncategorized", response_model=Page[UncategorizedJobOut])
def uncategorized_jobs(
    page: Pagination = Depends(pagination),
    admin: User = Depends(_manage),
    db: Session = Depends(get_db),
) -> Page[UncategorizedJobOut]:
    base = select(Job).where(Job.is_uncategorized.is_(True))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Job.created_at.desc()).limit(page.page_size).offset(page.offset)
    ).all()
    items = [
        UncategorizedJobOut(
            id=j.id,
            title=j.title,
            company_name=j.company.name if j.company else j.company_name_raw,
            origin=j.origin.value,
            created_at=j.created_at,
        )
        for j in rows
    ]
    return Page.build(items, total, page.page, page.page_size)
