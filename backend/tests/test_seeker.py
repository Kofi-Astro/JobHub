"""Seeker account endpoints: saved jobs, saved searches/alerts, anon merge."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Job, Source
from app.models.enums import JobOrigin, JobStatus


@pytest.fixture
def seeker_auth(client, seeded):
    """Register a seeker and return an Authorization header dict."""
    resp = client.post(
        "/api/auth/register/seeker",
        json={"email": "seeker@example.com", "password": "hunter2pass"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def two_jobs(seeded):
    db = seeded
    src = db.scalar(select(Source).where(Source.key == "remotive"))
    jobs = []
    for i in range(2):
        j = Job(
            origin=JobOrigin.AGGREGATED,
            source_id=src.id,
            external_id=f"seeker-test-{i}",
            title=f"Job {i}",
            company_name_raw="Acme",
            description_text="",
            status=JobStatus.ACTIVE,
        )
        db.add(j)
        jobs.append(j)
    db.flush()
    return jobs


def test_saved_jobs_require_auth(client, two_jobs):
    assert client.get("/api/seeker/saved-jobs").status_code == 401
    assert (
        client.post("/api/seeker/saved-jobs", json={"job_id": str(two_jobs[0].id)}).status_code
        == 401
    )


def test_save_list_and_unsave_job(client, seeker_auth, two_jobs):
    job = two_jobs[0]
    resp = client.post("/api/seeker/saved-jobs", json={"job_id": str(job.id)}, headers=seeker_auth)
    assert resp.status_code == 201
    assert resp.json()["job"]["id"] == str(job.id)

    listed = client.get("/api/seeker/saved-jobs", headers=seeker_auth).json()
    assert len(listed) == 1 and listed[0]["job"]["title"] == job.title

    # Saving the same job again is idempotent, not a duplicate.
    again = client.post("/api/seeker/saved-jobs", json={"job_id": str(job.id)}, headers=seeker_auth)
    assert again.status_code == 201
    assert len(client.get("/api/seeker/saved-jobs", headers=seeker_auth).json()) == 1

    assert client.delete(f"/api/seeker/saved-jobs/{job.id}", headers=seeker_auth).status_code == 200
    assert client.get("/api/seeker/saved-jobs", headers=seeker_auth).json() == []


def test_save_nonexistent_job_404s(client, seeker_auth):
    resp = client.post(
        "/api/seeker/saved-jobs",
        json={"job_id": "00000000-0000-0000-0000-000000000000"},
        headers=seeker_auth,
    )
    assert resp.status_code == 404


def test_employer_token_cannot_use_seeker_routes(client, seeded):
    reg = client.post(
        "/api/auth/register/employer",
        json={"email": "emp@example.com", "password": "hunter2pass", "company_name": "Acme"},
    )
    token = reg.json()["access_token"]
    resp = client.get("/api/seeker/saved-jobs", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_saved_search_crud_and_alert_validation(client, seeker_auth):
    resp = client.post(
        "/api/seeker/saved-searches",
        json={"name": "Remote Python", "query_params": {"q": "python", "remote": True}},
        headers=seeker_auth,
    )
    assert resp.status_code == 201
    search_id = resp.json()["id"]
    assert resp.json()["alert_enabled"] is False

    # Turning on alerts without a frequency is rejected.
    bad = client.post(
        "/api/seeker/saved-searches",
        json={"name": "x", "query_params": {}, "alert_enabled": True},
        headers=seeker_auth,
    )
    assert bad.status_code == 422

    updated = client.patch(
        f"/api/seeker/saved-searches/{search_id}",
        json={"alert_enabled": True, "alert_frequency": "weekly"},
        headers=seeker_auth,
    )
    assert updated.status_code == 200
    assert updated.json()["alert_frequency"] == "weekly"

    listed = client.get("/api/seeker/saved-searches", headers=seeker_auth).json()
    assert len(listed) == 1

    assert (
        client.delete(f"/api/seeker/saved-searches/{search_id}", headers=seeker_auth).status_code
        == 200
    )
    assert client.get("/api/seeker/saved-searches", headers=seeker_auth).json() == []


def test_saved_search_not_visible_to_other_seekers(client, seeded):
    a = client.post(
        "/api/auth/register/seeker", json={"email": "a@example.com", "password": "hunter2pass"}
    ).json()["access_token"]
    b = client.post(
        "/api/auth/register/seeker", json={"email": "b@example.com", "password": "hunter2pass"}
    ).json()["access_token"]

    client.post(
        "/api/seeker/saved-searches",
        json={"name": "mine", "query_params": {}},
        headers={"Authorization": f"Bearer {a}"},
    )
    assert (
        client.get("/api/seeker/saved-searches", headers={"Authorization": f"Bearer {b}"}).json()
        == []
    )


def test_merge_anon_adds_only_new_and_valid_jobs(client, seeker_auth, two_jobs):
    job = two_jobs[0]
    # Pre-save one of the two so the merge should only add the other.
    client.post("/api/seeker/saved-jobs", json={"job_id": str(job.id)}, headers=seeker_auth)

    resp = client.post(
        "/api/seeker/merge-anon",
        json={
            "saved_job_ids": [
                str(job.id),
                str(two_jobs[1].id),
                "00000000-0000-0000-0000-000000000000",  # doesn't exist — ignored
            ]
        },
        headers=seeker_auth,
    )
    assert resp.status_code == 200
    assert resp.json()["saved_jobs_merged"] == 1

    saved = client.get("/api/seeker/saved-jobs", headers=seeker_auth).json()
    assert {s["job"]["id"] for s in saved} == {str(j.id) for j in two_jobs}
