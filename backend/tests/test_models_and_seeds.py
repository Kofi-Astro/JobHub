"""Milestone 2: the data model holds together and the seeds load."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import Field, Job, Source, Subfield, User
from app.models.enums import JobOrigin, JobStatus, UserRole


def test_seeds_load_taxonomy_and_sources(seeded):
    db = seeded
    assert db.scalar(select(func.count()).select_from(Field)) >= 12
    assert db.scalar(select(func.count()).select_from(Subfield)) >= 60
    # Every sub-field carries classifier keywords.
    assert (
        db.scalar(
            select(func.count())
            .select_from(Subfield)
            .where(func.cardinality(Subfield.keywords) == 0)
        )
        == 0
    )
    # Keyless aggregators/ATS enabled; keyed ones disabled.
    remotive = db.scalar(select(Source).where(Source.key == "remotive"))
    assert remotive.enabled is True and remotive.requires_api_key is False
    adzuna = db.scalar(select(Source).where(Source.key == "adzuna"))
    assert adzuna.enabled is False and adzuna.api_key_ref == "ADZUNA_APP_KEY"


def test_seed_rerun_is_idempotent(db):
    from app.seeds.run import seed_taxonomy

    seed_taxonomy(db)
    db.flush()
    first = db.scalar(select(func.count()).select_from(Subfield))
    seed_taxonomy(db)
    db.flush()
    assert db.scalar(select(func.count()).select_from(Subfield)) == first


def test_search_vector_is_generated_on_insert(seeded):
    db = seeded
    src = db.scalar(select(Source).where(Source.key == "remotive"))
    job = Job(
        origin=JobOrigin.AGGREGATED,
        source_id=src.id,
        external_id="abc-123",
        title="Senior Python Engineer",
        company_name_raw="Acme",
        description_text="We need someone strong in FastAPI and Postgres.",
        status=JobStatus.ACTIVE,
    )
    db.add(job)
    db.flush()
    db.refresh(job)
    # The generated tsvector picks up the title tokens.
    row = db.execute(
        select(Job.id).where(
            Job.search_vector.op("@@")(func.plainto_tsquery("english", "python engineer"))
        )
    ).first()
    assert row is not None and row[0] == job.id


def test_origin_consistency_check_constraint(seeded):
    db = seeded
    # origin=employer must NOT carry a source_id.
    bad = Job(
        origin=JobOrigin.EMPLOYER,
        source_id=db.scalar(select(Source.id).limit(1)),
        posted_by_user_id=uuid.uuid4(),
        title="x",
    )
    db.add(bad)
    with pytest.raises(IntegrityError):
        db.flush()


def test_email_is_case_insensitive_unique(db):
    db.add(User(role=UserRole.SEEKER, email="Ada@Example.com"))
    db.flush()
    db.add(User(role=UserRole.SEEKER, email="ada@example.com"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_company_match_key_dedupes_legal_suffixes():
    from app.util.text import normalize_company_name

    assert normalize_company_name("Acme, Inc.") == normalize_company_name("Acme")
    assert normalize_company_name("Globex LLC") == "globex"
