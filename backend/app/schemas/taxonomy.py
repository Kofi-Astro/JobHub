"""Taxonomy response models — the field/sub-field tree the frontend renders in
the filter sidebar and the employer posting form."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class SubfieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    display_order: int


class FieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    icon: str | None
    display_order: int
    subfields: list[SubfieldOut]


class TaxonomyTree(BaseModel):
    fields: list[FieldOut]
