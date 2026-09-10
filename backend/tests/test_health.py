"""Milestone 1 smoke test: the app boots and the health probe works."""

from __future__ import annotations

from app import __version__


def test_health_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


def test_version(client):
    resp = client.get("/api/version")
    assert resp.status_code == 200
    assert resp.json() == {"version": __version__}


def test_openapi_served_outside_production(client):
    # docs are on in test/local, off in production (see create_app)
    assert client.get("/openapi.json").status_code == 200
