"""Admin site content + announcements, and the public reads of both."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def test_set_and_list_site_content(client, seeded, admin_auth):
    resp = client.put(
        "/api/admin/content/homepage.featured_fields",
        json={"value": ["computing-tech", "design"]},
        headers=admin_auth,
    )
    assert resp.status_code == 200
    assert resp.json()["value"] == ["computing-tech", "design"]

    listed = client.get("/api/admin/content", headers=admin_auth).json()
    assert any(c["key"] == "homepage.featured_fields" for c in listed)

    public = client.get("/api/content/homepage.featured_fields")
    assert public.status_code == 200
    assert public.json()["value"] == ["computing-tech", "design"]


def test_unset_content_key_returns_null_publicly(client, seeded):
    resp = client.get("/api/content/no.such.key")
    assert resp.status_code == 200
    assert resp.json() is None


def test_announcement_lifecycle_and_public_visibility(client, seeded, admin_auth):
    create = client.post(
        "/api/admin/announcements",
        json={"title": "Maintenance", "body": "Down for maintenance.", "is_active": True},
        headers=admin_auth,
    )
    assert create.status_code == 201
    ann_id = create.json()["id"]

    active = client.get("/api/announcements/active")
    assert active.status_code == 200
    assert active.json()["title"] == "Maintenance"

    update = client.patch(
        f"/api/admin/announcements/{ann_id}",
        json={"title": "Maintenance", "body": "Done.", "is_active": False},
        headers=admin_auth,
    )
    assert update.status_code == 200
    assert client.get("/api/announcements/active").json() is None

    delete = client.delete(f"/api/admin/announcements/{ann_id}", headers=admin_auth)
    assert delete.status_code == 200
    assert client.get("/api/admin/announcements", headers=admin_auth).json() == []


def test_announcement_outside_its_date_window_is_not_active(client, seeded, admin_auth):
    future = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    client.post(
        "/api/admin/announcements",
        json={"title": "Future", "body": "Not yet.", "is_active": True, "starts_at": future},
        headers=admin_auth,
    )
    assert client.get("/api/announcements/active").json() is None
