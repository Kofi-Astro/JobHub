"""Auth: register (seeker/employer), login, refresh rotation, logout, /me,
role guards, and password hashing."""

from __future__ import annotations

from sqlalchemy import select

from app.models import EmployerProfile, RefreshToken, User
from app.models.enums import EmployerAccountStatus, UserRole
from app.services.auth import hash_password, verify_password


def test_password_hash_roundtrip():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong password", h) is False
    assert verify_password("anything", None) is False


def test_register_seeker_creates_user_and_tokens(client, seeded):
    resp = client.post(
        "/api/auth/register/seeker",
        json={"email": "ada@example.com", "password": "hunter2pass", "full_name": "Ada"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"]["role"] == "seeker"
    assert body["access_token"]
    assert "refresh_token" in resp.cookies

    user = seeded.scalar(select(User).where(User.email == "ada@example.com"))
    assert user is not None and user.role == UserRole.SEEKER


def test_register_seeker_duplicate_email_conflicts(client, seeded):
    payload = {"email": "dup@example.com", "password": "hunter2pass"}
    assert client.post("/api/auth/register/seeker", json=payload).status_code == 201
    resp = client.post("/api/auth/register/seeker", json=payload)
    assert resp.status_code == 409


def test_register_seeker_short_password_rejected(client, seeded):
    resp = client.post(
        "/api/auth/register/seeker", json={"email": "x@example.com", "password": "short"}
    )
    assert resp.status_code == 422


def test_register_employer_creates_pending_profile(client, seeded):
    resp = client.post(
        "/api/auth/register/employer",
        json={
            "email": "hr@acme.example",
            "password": "hunter2pass",
            "company_name": "Acme, Inc.",
            "job_title": "HR Lead",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["user"]["role"] == "employer"

    profile = seeded.scalar(
        select(EmployerProfile)
        .join(User, User.id == EmployerProfile.user_id)
        .where(User.email == "hr@acme.example")
    )
    assert profile is not None
    assert profile.account_status == EmployerAccountStatus.PENDING
    assert profile.company.name == "Acme, Inc."


def test_login_wrong_password_401(client, seeded):
    client.post(
        "/api/auth/register/seeker", json={"email": "bob@example.com", "password": "hunter2pass"}
    )
    resp = client.post("/api/auth/login", json={"email": "bob@example.com", "password": "nope"})
    assert resp.status_code == 401


def test_login_unknown_email_401_same_message_as_wrong_password(client, seeded):
    r1 = client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": "whatever1"}
    )
    r2 = client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": "whatever2"}
    )
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["detail"] == r2.json()["detail"]


def test_me_requires_auth(client, seeded):
    assert client.get("/api/auth/me").status_code == 401

    reg = client.post(
        "/api/auth/register/seeker", json={"email": "carol@example.com", "password": "hunter2pass"}
    )
    token = reg.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "carol@example.com"


def test_refresh_rotates_token_and_old_one_stops_working(client, seeded):
    reg = client.post(
        "/api/auth/register/seeker", json={"email": "dave@example.com", "password": "hunter2pass"}
    )
    old_cookie = reg.cookies.get("refresh_token")
    assert old_cookie

    r1 = client.post("/api/auth/refresh")
    assert r1.status_code == 200
    new_cookie = r1.cookies.get("refresh_token")
    assert new_cookie and new_cookie != old_cookie

    # Reusing the original (now-rotated-away) cookie must fail.
    client.cookies.set("refresh_token", old_cookie)
    r2 = client.post("/api/auth/refresh")
    assert r2.status_code == 401


def test_logout_revokes_refresh_token(client, seeded):
    client.post(
        "/api/auth/register/seeker", json={"email": "eve@example.com", "password": "hunter2pass"}
    )
    assert client.post("/api/auth/logout").status_code == 200
    assert client.post("/api/auth/refresh").status_code == 401


def test_expired_or_garbage_access_token_is_treated_as_anonymous(client, seeded):
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401  # require_user still 401s — just not a 500


def test_refresh_cookie_uses_samesite_none_cross_site_in_production(client, seeded, monkeypatch):
    """A SameSite=Lax refresh cookie is never sent by the browser on a
    cross-site fetch() — exactly what happens when the frontend and API are
    separate origins (the deployed architecture). Production must use
    SameSite=None (which requires Secure) so the silent-refresh-on-load flow
    the frontend relies on actually works once deployed. This only checks the
    header attributes FastAPI/Starlette emit; TestClient does not enforce
    SameSite the way a real browser does — that gap is exactly why this was
    initially missed and only caught by an end-to-end browser test."""
    import app.config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "production")
    try:
        resp = client.post(
            "/api/auth/register/seeker",
            json={"email": "prod-cookie@example.com", "password": "hunter2pass"},
        )
        assert resp.status_code == 201
        set_cookie = resp.headers.get("set-cookie", "")
        assert "samesite=none" in set_cookie.lower()
        assert "secure" in set_cookie.lower()
    finally:
        monkeypatch.setenv("ENVIRONMENT", "test")
        config_module.get_settings.cache_clear()


def test_refresh_cookie_uses_samesite_lax_locally(client, seeded):
    resp = client.post(
        "/api/auth/register/seeker",
        json={"email": "local-cookie@example.com", "password": "hunter2pass"},
    )
    set_cookie = resp.headers.get("set-cookie", "")
    assert "samesite=lax" in set_cookie.lower()
    assert "secure" not in set_cookie.lower()


def test_refresh_token_is_stored_hashed_not_raw(client, seeded):
    reg = client.post(
        "/api/auth/register/seeker", json={"email": "frank@example.com", "password": "hunter2pass"}
    )
    raw = reg.cookies.get("refresh_token")
    rows = seeded.scalars(select(RefreshToken)).all()
    assert rows and all(r.token_hash != raw for r in rows)
