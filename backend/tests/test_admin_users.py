"""Admin user management: list/disable/enable/reset-password, and superadmin-
only admin-account management."""

from __future__ import annotations

from sqlalchemy import select

from app.models import User
from app.models.enums import AdminRole, UserRole
from app.services.auth import create_access_token, hash_password


def test_list_users_excludes_admins_and_supports_role_filter(client, seeded, admin_auth):
    client.post(
        "/api/auth/register/seeker", json={"email": "s1@example.com", "password": "hunter2pass"}
    )
    client.post(
        "/api/auth/register/employer",
        json={"email": "e1@example.com", "password": "hunter2pass", "company_name": "Acme"},
    )

    all_users = client.get("/api/admin/users", headers=admin_auth).json()
    assert all(u["role"] != "admin" for u in all_users)
    assert {u["email"] for u in all_users} == {"s1@example.com", "e1@example.com"}

    employers_only = client.get("/api/admin/users?role=employer", headers=admin_auth).json()
    assert len(employers_only) == 1 and employers_only[0]["employer_account_status"] == "pending"


def test_disable_user_revokes_session_and_blocks_login(client, seeded, admin_auth):
    reg = client.post(
        "/api/auth/register/seeker", json={"email": "bad@example.com", "password": "hunter2pass"}
    )
    user_id = seeded.scalar(select(User.id).where(User.email == "bad@example.com"))

    resp = client.post(f"/api/admin/users/{user_id}/disable", headers=admin_auth)
    assert resp.status_code == 200

    login = client.post(
        "/api/auth/login", json={"email": "bad@example.com", "password": "hunter2pass"}
    )
    assert login.status_code == 403

    old_token = reg.json()["access_token"]
    assert (
        client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"}).status_code
        == 401
    )


def test_enable_user_restores_login(client, seeded, admin_auth):
    client.post(
        "/api/auth/register/seeker", json={"email": "back@example.com", "password": "hunter2pass"}
    )
    user_id = seeded.scalar(select(User.id).where(User.email == "back@example.com"))
    client.post(f"/api/admin/users/{user_id}/disable", headers=admin_auth)

    client.post(f"/api/admin/users/{user_id}/enable", headers=admin_auth)
    login = client.post(
        "/api/auth/login", json={"email": "back@example.com", "password": "hunter2pass"}
    )
    assert login.status_code == 200


def test_reset_password_returns_working_temp_password(client, seeded, admin_auth):
    client.post(
        "/api/auth/register/seeker", json={"email": "forgot@example.com", "password": "hunter2pass"}
    )
    user_id = seeded.scalar(select(User.id).where(User.email == "forgot@example.com"))

    resp = client.post(f"/api/admin/users/{user_id}/reset-password", headers=admin_auth)
    assert resp.status_code == 200
    temp = resp.json()["temporary_password"]

    old_login = client.post(
        "/api/auth/login", json={"email": "forgot@example.com", "password": "hunter2pass"}
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/auth/login", json={"email": "forgot@example.com", "password": temp}
    )
    assert new_login.status_code == 200


def test_only_superadmin_permission_can_manage_admins(client, seeded):
    editor = User(
        role=UserRole.ADMIN,
        email="editor@jobhub.example",
        password_hash=hash_password("adminpass1"),
    )
    seeded.add(editor)
    seeded.flush()
    from app.models import AdminProfile

    seeded.add(AdminProfile(user_id=editor.id, admin_role=AdminRole.EDITOR))
    seeded.commit()
    token, _ = create_access_token(editor)

    resp = client.get("/api/admin/users/admins", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_superadmin_can_create_and_list_admins(client, seeded, admin_auth):
    resp = client.post(
        "/api/admin/users/admins",
        json={
            "email": "newadmin@jobhub.example",
            "password": "adminpass123",
            "admin_role": "editor",
        },
        headers=admin_auth,
    )
    assert resp.status_code == 201
    assert resp.json()["admin_role"] == "editor"

    admins = client.get("/api/admin/users/admins", headers=admin_auth).json()
    assert any(a["email"] == "newadmin@jobhub.example" for a in admins)
