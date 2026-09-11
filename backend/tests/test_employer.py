"""Employer posting portal + admin moderation queue: the whole lifecycle of a
listing from a brand-new (unapproved) employer through to a live, canonical
job, plus the "second posting from a trusted employer skips review" rule."""

from __future__ import annotations

from sqlalchemy import select

from app.models import AdminProfile, EmployerProfile, Job, User
from app.models.enums import (
    AdminRole,
    EmployerAccountStatus,
    JobStatus,
    ModerationStatus,
    UserRole,
)
from app.services.auth import hash_password


def _register_employer(client, email="hr@acme.example", company="Acme Inc"):
    resp = client.post(
        "/api/auth/register/employer",
        json={"email": email, "password": "hunter2pass", "company_name": company},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _make_admin(db) -> dict:
    user = User(
        role=UserRole.ADMIN, email="admin@jobhub.example", password_hash=hash_password("adminpass1")
    )
    db.add(user)
    db.flush()
    db.add(AdminProfile(user_id=user.id, admin_role=AdminRole.MODERATOR))
    db.commit()
    from app.services.auth import create_access_token

    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


VALID_POST = {
    "title": "Senior Backend Engineer",
    "description_html": "<p>Build our API in Python.</p>",
    "field_slug": "computing-tech",
    "subfield_slug": "software-engineering",
    "workplace_type": "remote",
    "remote_scope": "Worldwide",
    "job_type": "full_time",
    "experience_level": "senior",
    "salary_is_disclosed": True,
    "salary_min": "120000",
    "salary_max": "160000",
    "salary_currency": "USD",
    "salary_period": "year",
    "apply_url": "https://acme.example/careers/backend-engineer",
}


def test_new_employer_posting_requires_moderation_and_is_invisible(client, seeded):
    auth = _register_employer(client)
    resp = client.post("/api/employer/jobs", json=VALID_POST, headers=auth)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "pending" and body["moderation_status"] == "pending"

    # Not visible in public search while pending.
    assert client.get("/api/jobs").json()["total"] == 0


def test_posting_form_requires_an_application_path(client, seeded):
    auth = _register_employer(client)
    bad = {**VALID_POST, "apply_url": None}
    resp = client.post("/api/employer/jobs", json=bad, headers=auth)
    assert resp.status_code == 422


def test_onsite_posting_requires_a_location(client, seeded):
    auth = _register_employer(client)
    bad = {**VALID_POST, "workplace_type": "onsite", "city": None, "country_code": None}
    resp = client.post("/api/employer/jobs", json=bad, headers=auth)
    assert resp.status_code == 422


def test_admin_approval_flow_end_to_end(client, seeded):
    auth = _register_employer(client)
    admin_auth = _make_admin(seeded)

    job_id = client.post("/api/employer/jobs", json=VALID_POST, headers=auth).json()["id"]

    # A non-admin cannot moderate.
    assert client.post(f"/api/admin/jobs/{job_id}/approve", headers=auth).status_code == 403

    pending_employers = client.get("/api/admin/employers/pending", headers=admin_auth).json()
    assert any(p["email"] == "hr@acme.example" for p in pending_employers)
    user_id = pending_employers[0]["user_id"]

    assert (
        client.post(f"/api/admin/employers/{user_id}/approve", headers=admin_auth).status_code
        == 200
    )

    pending_jobs = client.get("/api/admin/jobs/pending", headers=admin_auth).json()
    assert any(j["id"] == job_id for j in pending_jobs)

    assert client.post(f"/api/admin/jobs/{job_id}/approve", headers=admin_auth).status_code == 200

    # Now live and visible, with the "Direct from employer" badge.
    listed = client.get("/api/jobs").json()
    assert listed["total"] == 1
    assert listed["items"][0]["is_direct_from_employer"] is True

    profile = seeded.get(EmployerProfile, uuid_of(user_id))
    assert profile.account_status == EmployerAccountStatus.APPROVED

    job = seeded.get(Job, uuid_of(job_id))
    assert job.status == JobStatus.ACTIVE and job.moderation_status == ModerationStatus.APPROVED


def test_second_posting_from_a_trusted_employer_skips_review(client, seeded):
    auth = _register_employer(client, email="trusted@acme.example")
    admin_auth = _make_admin(seeded)

    first_id = client.post("/api/employer/jobs", json=VALID_POST, headers=auth).json()["id"]
    user_id = seeded.scalar(
        select(EmployerProfile.user_id)
        .join(User, User.id == EmployerProfile.user_id)
        .where(User.email == "trusted@acme.example")
    )
    client.post(f"/api/admin/employers/{user_id}/approve", headers=admin_auth)
    client.post(f"/api/admin/jobs/{first_id}/approve", headers=admin_auth)

    second = client.post(
        "/api/employer/jobs",
        json={**VALID_POST, "title": "Second Role"},
        headers=auth,
    )
    assert second.status_code == 201
    assert second.json()["status"] == "active"
    assert second.json()["moderation_status"] == "approved"


def test_reject_employer_account_records_reason(client, seeded):
    _register_employer(client, email="spammy@example.com")  # creates the pending account
    admin_auth = _make_admin(seeded)
    user_id = seeded.scalar(
        select(EmployerProfile.user_id)
        .join(User, User.id == EmployerProfile.user_id)
        .where(User.email == "spammy@example.com")
    )

    resp = client.post(
        f"/api/admin/employers/{user_id}/reject",
        json={"reason": "Looks fraudulent"},
        headers=admin_auth,
    )
    assert resp.status_code == 200
    profile = seeded.get(EmployerProfile, user_id)
    assert profile.account_status == EmployerAccountStatus.REJECTED
    assert profile.rejection_reason == "Looks fraudulent"


def test_close_and_republish_lifecycle(client, seeded):
    auth = _register_employer(client)
    admin_auth = _make_admin(seeded)
    job_id = client.post("/api/employer/jobs", json=VALID_POST, headers=auth).json()["id"]
    user_id = seeded.scalar(select(EmployerProfile.user_id))
    client.post(f"/api/admin/employers/{user_id}/approve", headers=admin_auth)
    client.post(f"/api/admin/jobs/{job_id}/approve", headers=admin_auth)

    assert client.get("/api/jobs").json()["total"] == 1

    closed = client.post(f"/api/employer/jobs/{job_id}/close", headers=auth)
    assert closed.status_code == 200 and closed.json()["status"] == "closed"
    assert client.get("/api/jobs").json()["total"] == 0

    # Editing a closed listing is refused until it's republished.
    assert (
        client.patch(f"/api/employer/jobs/{job_id}", json={"title": "xx"}, headers=auth).status_code
        == 409
    )

    republished = client.post(f"/api/employer/jobs/{job_id}/republish", headers=auth)
    assert republished.status_code == 200 and republished.json()["status"] == "active"
    assert client.get("/api/jobs").json()["total"] == 1


def test_posting_quota_enforced_when_set(client, seeded):
    auth = _register_employer(client)
    user_id = seeded.scalar(select(EmployerProfile.user_id))
    seeded.get(EmployerProfile, user_id).posting_quota = 1
    seeded.commit()

    first = client.post("/api/employer/jobs", json=VALID_POST, headers=auth)
    assert first.status_code == 201

    second = client.post(
        "/api/employer/jobs", json={**VALID_POST, "title": "Another Role"}, headers=auth
    )
    assert second.status_code == 422
    assert "limit" in second.json()["detail"].lower()


def test_employer_cannot_see_or_edit_another_employers_job(client, seeded):
    auth_a = _register_employer(client, email="a@example.com", company="A Co")
    auth_b = _register_employer(client, email="b@example.com", company="B Co")
    job_id = client.post("/api/employer/jobs", json=VALID_POST, headers=auth_a).json()["id"]

    assert client.get(f"/api/employer/jobs/{job_id}", headers=auth_b).status_code == 404
    assert client.post(f"/api/employer/jobs/{job_id}/close", headers=auth_b).status_code == 404


def test_seeker_cannot_use_employer_routes(client, seeded):
    seeker = client.post(
        "/api/auth/register/seeker", json={"email": "s@example.com", "password": "hunter2pass"}
    ).json()["access_token"]
    resp = client.post(
        "/api/employer/jobs", json=VALID_POST, headers={"Authorization": f"Bearer {seeker}"}
    )
    assert resp.status_code == 403


def uuid_of(s):
    import uuid

    return uuid.UUID(s) if isinstance(s, str) else s
