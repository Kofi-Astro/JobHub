"""Admin source registry: create/edit/disable, health/run history, run-now."""

from __future__ import annotations

import respx
from sqlalchemy import select

from app.models import Source
from tests.conftest_ingestion import load_fixture


def test_list_sources_shows_health_fields(client, seeded, admin_auth):
    rows = client.get("/api/admin/sources", headers=admin_auth).json()
    remotive = next(r for r in rows if r["key"] == "remotive")
    assert remotive["enabled"] is True
    assert "consecutive_failures" in remotive and "last_run_at" in remotive


def test_create_source_never_auto_enables(client, seeded, admin_auth):
    resp = client.post(
        "/api/admin/sources",
        json={
            "key": "newsource",
            "name": "New Source",
            "adapter": "remotive",
            "kind": "aggregator",
        },
        headers=admin_auth,
    )
    assert resp.status_code == 201
    assert resp.json()["enabled"] is False


def test_create_source_duplicate_key_conflicts(client, seeded, admin_auth):
    resp = client.post(
        "/api/admin/sources",
        json={"key": "remotive", "name": "Dup", "adapter": "remotive", "kind": "aggregator"},
        headers=admin_auth,
    )
    assert resp.status_code == 409


def test_cannot_enable_keyed_source_without_the_credential_value_set(client, seeded, admin_auth):
    # adzuna is seeded with api_key_ref="ADZUNA_APP_KEY" already (it always is,
    # per ARCHITECTURE.md) — but the ADZUNA_APP_KEY env var itself is blank in
    # tests, so enabling must still be refused.
    adzuna = seeded.scalar(select(Source).where(Source.key == "adzuna"))
    resp = client.patch(
        f"/api/admin/sources/{adzuna.id}", json={"enabled": True}, headers=admin_auth
    )
    assert resp.status_code == 422


def test_can_enable_keyed_source_once_the_credential_is_set(
    client, seeded, admin_auth, monkeypatch
):
    import app.config as config_module

    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key-value")
    config_module.get_settings.cache_clear()
    try:
        adzuna = seeded.scalar(select(Source).where(Source.key == "adzuna"))
        resp = client.patch(
            f"/api/admin/sources/{adzuna.id}", json={"enabled": True}, headers=admin_auth
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True
    finally:
        config_module.get_settings.cache_clear()


def test_update_source_rate_limit_and_interval(client, seeded, admin_auth):
    remotive = seeded.scalar(select(Source).where(Source.key == "remotive"))
    resp = client.patch(
        f"/api/admin/sources/{remotive.id}",
        json={"rate_limit_per_min": 5, "refresh_interval_minutes": 720, "tier": "paid"},
        headers=admin_auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rate_limit_per_min"] == 5
    assert body["refresh_interval_minutes"] == 720
    assert body["tier"] == "paid"


@respx.mock
def test_run_now_triggers_an_immediate_run_and_appears_in_history(client, seeded, admin_auth):
    respx.get("https://remotive.com/api/remote-jobs").respond(json=load_fixture("remotive.json"))
    remotive = seeded.scalar(select(Source).where(Source.key == "remotive"))

    resp = client.post(f"/api/admin/sources/{remotive.id}/run-now", headers=admin_auth)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert resp.json()["jobs_created"] == 2

    runs = client.get(f"/api/admin/sources/{remotive.id}/runs", headers=admin_auth).json()
    assert len(runs) == 1


def test_run_now_refuses_a_disabled_source(client, seeded, admin_auth):
    remotive = seeded.scalar(select(Source).where(Source.key == "remotive"))
    client.patch(f"/api/admin/sources/{remotive.id}", json={"enabled": False}, headers=admin_auth)
    resp = client.post(f"/api/admin/sources/{remotive.id}/run-now", headers=admin_auth)
    assert resp.status_code == 409


def test_analyst_role_can_view_but_not_manage_sources(client, seeded):
    from app.models import AdminProfile, User
    from app.models.enums import AdminRole, UserRole
    from app.services.auth import create_access_token, hash_password

    admin = User(
        role=UserRole.ADMIN,
        email="analyst@jobhub.example",
        password_hash=hash_password("adminpass1"),
    )
    seeded.add(admin)
    seeded.flush()
    seeded.add(AdminProfile(user_id=admin.id, admin_role=AdminRole.ANALYST))
    seeded.commit()
    token, _ = create_access_token(admin)
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/admin/sources", headers=headers).status_code == 403
