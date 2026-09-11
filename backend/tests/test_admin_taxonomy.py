"""Admin taxonomy management: CRUD on fields/sub-fields, remap-before-delete,
and the uncategorized-jobs review queue."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Field, Job, Source, Subfield
from app.models.enums import JobOrigin, JobStatus


def test_list_taxonomy_requires_permission(client, seeded):
    assert client.get("/api/admin/taxonomy").status_code == 401


def test_list_taxonomy_includes_inactive(client, seeded, admin_auth):
    field = seeded.scalar(select(Field).where(Field.slug == "computing-tech"))
    field.is_active = False
    seeded.commit()

    body = client.get("/api/admin/taxonomy", headers=admin_auth).json()
    tech = next(f for f in body if f["slug"] == "computing-tech")
    assert tech["is_active"] is False
    assert any(sf["slug"] == "web-development" for sf in tech["subfields"])


def test_create_field_and_duplicate_slug_conflicts(client, seeded, admin_auth):
    resp = client.post(
        "/api/admin/taxonomy/fields",
        json={"slug": "new-field", "name": "New Field"},
        headers=admin_auth,
    )
    assert resp.status_code == 201
    assert resp.json()["subfields"] == []

    dup = client.post(
        "/api/admin/taxonomy/fields", json={"slug": "new-field", "name": "Dup"}, headers=admin_auth
    )
    assert dup.status_code == 409


def test_update_field(client, seeded, admin_auth):
    field = seeded.scalar(select(Field).where(Field.slug == "design"))
    resp = client.patch(
        f"/api/admin/taxonomy/fields/{field.id}", json={"is_active": False}, headers=admin_auth
    )
    assert resp.status_code == 200
    seeded.refresh(field)
    assert field.is_active is False


def test_delete_field_blocked_while_subfields_exist(client, seeded, admin_auth):
    field = seeded.scalar(select(Field).where(Field.slug == "design"))
    resp = client.delete(f"/api/admin/taxonomy/fields/{field.id}", headers=admin_auth)
    assert resp.status_code == 409


def test_create_subfield_under_unknown_field_404s(client, seeded, admin_auth):
    resp = client.post(
        "/api/admin/taxonomy/subfields",
        json={"field_id": "00000000-0000-0000-0000-000000000000", "slug": "x", "name": "X"},
        headers=admin_auth,
    )
    assert resp.status_code == 404


def test_delete_subfield_blocked_while_jobs_reference_it_then_remap_unblocks(
    client, seeded, admin_auth
):
    webdev = seeded.scalar(select(Subfield).where(Subfield.slug == "web-development"))
    devops = seeded.scalar(select(Subfield).where(Subfield.slug == "devops"))
    src = seeded.scalar(select(Source).where(Source.key == "remotive"))
    job = Job(
        origin=JobOrigin.AGGREGATED,
        source_id=src.id,
        external_id="t1",
        title="x",
        company_name_raw="Acme",
        description_text="",
        status=JobStatus.ACTIVE,
        field_id=webdev.field_id,
        subfield_id=webdev.id,
    )
    seeded.add(job)
    seeded.commit()

    blocked = client.delete(f"/api/admin/taxonomy/subfields/{webdev.id}", headers=admin_auth)
    assert blocked.status_code == 409

    remap = client.post(
        f"/api/admin/taxonomy/subfields/{webdev.id}/remap",
        json={"target_subfield_id": str(devops.id)},
        headers=admin_auth,
    )
    assert remap.status_code == 200 and "1" in remap.json()["detail"]

    seeded.refresh(job)
    assert job.subfield_id == devops.id
    assert job.field_id == devops.field_id

    now_ok = client.delete(f"/api/admin/taxonomy/subfields/{webdev.id}", headers=admin_auth)
    assert now_ok.status_code == 200


def test_uncategorized_queue_lists_only_flagged_jobs(client, seeded, admin_auth):
    src = seeded.scalar(select(Source).where(Source.key == "remotive"))
    seeded.add(
        Job(
            origin=JobOrigin.AGGREGATED,
            source_id=src.id,
            external_id="u1",
            title="Mystery role",
            company_name_raw="Acme",
            description_text="",
            status=JobStatus.ACTIVE,
            is_uncategorized=True,
        )
    )
    seeded.add(
        Job(
            origin=JobOrigin.AGGREGATED,
            source_id=src.id,
            external_id="u2",
            title="Clear role",
            company_name_raw="Acme",
            description_text="",
            status=JobStatus.ACTIVE,
            is_uncategorized=False,
        )
    )
    seeded.commit()

    body = client.get("/api/admin/taxonomy/uncategorized", headers=admin_auth).json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Mystery role"


def test_moderator_role_cannot_manage_taxonomy(client, seeded):
    """RBAC: `taxonomy.manage` belongs to editor/superadmin, not moderator."""
    from app.models import AdminProfile, User
    from app.models.enums import AdminRole, UserRole
    from app.services.auth import create_access_token, hash_password

    admin = User(
        role=UserRole.ADMIN, email="mod@jobhub.example", password_hash=hash_password("adminpass1")
    )
    seeded.add(admin)
    seeded.flush()
    seeded.add(AdminProfile(user_id=admin.id, admin_role=AdminRole.MODERATOR))
    seeded.commit()
    token, _ = create_access_token(admin)

    resp = client.get("/api/admin/taxonomy", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
