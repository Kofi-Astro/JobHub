"""Admin general job management: list/filter, edit, hide/unhide, manual
categorization."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Field, Job, Source, Subfield
from app.models.enums import JobOrigin, JobStatus


def _job(db, *, status=JobStatus.ACTIVE, title="Backend Engineer", is_uncategorized=True):
    src = db.scalar(select(Source).where(Source.key == "remotive"))
    j = Job(
        origin=JobOrigin.AGGREGATED,
        source_id=src.id,
        external_id=title,
        title=title,
        company_name_raw="Acme",
        description_text="",
        status=status,
        is_uncategorized=is_uncategorized,
        is_canonical=(status == JobStatus.ACTIVE),
    )
    db.add(j)
    db.flush()
    return j


def test_list_jobs_filters_by_status_and_query(client, seeded, admin_auth):
    _job(seeded, title="Senior Backend Engineer")
    _job(seeded, title="Marketing Manager", status=JobStatus.HIDDEN)
    seeded.commit()

    active = client.get("/api/admin/jobs?status=active", headers=admin_auth).json()
    assert active["total"] == 1

    by_q = client.get("/api/admin/jobs?q=Marketing", headers=admin_auth).json()
    assert by_q["total"] == 1 and by_q["items"][0]["status"] == "hidden"


def test_hide_and_unhide_job_affects_public_search(client, seeded, admin_auth):
    job = _job(seeded, is_uncategorized=False)
    seeded.commit()

    assert client.get("/api/jobs").json()["total"] == 1

    hide = client.post(f"/api/admin/jobs/{job.id}/hide", headers=admin_auth)
    assert hide.status_code == 200
    assert client.get("/api/jobs").json()["total"] == 0

    unhide = client.post(f"/api/admin/jobs/{job.id}/unhide", headers=admin_auth)
    assert unhide.status_code == 200
    assert client.get("/api/jobs").json()["total"] == 1


def test_unhide_a_non_hidden_job_conflicts(client, seeded, admin_auth):
    job = _job(seeded)
    seeded.commit()
    resp = client.post(f"/api/admin/jobs/{job.id}/unhide", headers=admin_auth)
    assert resp.status_code == 409


def test_update_job_title_and_status(client, seeded, admin_auth):
    job = _job(seeded)
    seeded.commit()
    resp = client.patch(
        f"/api/admin/jobs/{job.id}", json={"title": "Corrected Title"}, headers=admin_auth
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Corrected Title"


def test_categorize_uncategorized_job(client, seeded, admin_auth):
    job = _job(seeded, is_uncategorized=True)
    seeded.commit()
    webdev = seeded.scalar(select(Subfield).where(Subfield.slug == "web-development"))
    field = seeded.get(Field, webdev.field_id)

    resp = client.post(
        f"/api/admin/jobs/{job.id}/categorize",
        json={"field_slug": field.slug, "subfield_slug": webdev.slug},
        headers=admin_auth,
    )
    assert resp.status_code == 200
    seeded.refresh(job)
    assert job.is_uncategorized is False
    assert job.subfield_id == webdev.id
    assert job.categorization_method.value == "admin"


def test_categorize_with_unknown_subfield_404s(client, seeded, admin_auth):
    job = _job(seeded)
    seeded.commit()
    resp = client.post(
        f"/api/admin/jobs/{job.id}/categorize",
        json={"field_slug": "computing-tech", "subfield_slug": "not-a-real-subfield"},
        headers=admin_auth,
    )
    assert resp.status_code == 404
