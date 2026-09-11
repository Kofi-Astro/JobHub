"""Admin: user + employer account management (brief: "view, disable, reset")
and admin-account management (superadmin only — brief: role-based access for
multiple admins implies someone must be able to create/manage the others).
"""

from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_admin_permission
from app.db import get_db
from app.models import AdminProfile, User
from app.models.enums import UserRole
from app.schemas.admin_ops import (
    AdminCreateIn,
    AdminOut,
    AdminUserOut,
    ResetPasswordOut,
)
from app.schemas.common import Message
from app.services.audit import log_action
from app.services.auth import hash_password, revoke_all_refresh_tokens

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])

_manage = require_admin_permission("users.manage")
_manage_admins = require_admin_permission("admins.manage")


def _to_out(user: User) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        full_name=user.full_name,
        is_active=user.is_active,
        employer_account_status=user.employer_profile.account_status
        if user.employer_profile
        else None,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.get("", response_model=list[AdminUserOut])
def list_users(
    role: UserRole | None = None,
    q: str | None = None,
    admin: User = Depends(_manage),
    db: Session = Depends(get_db),
) -> list[AdminUserOut]:
    stmt = select(User).where(User.role != UserRole.ADMIN)  # admins are managed separately, below
    if role is not None:
        stmt = stmt.where(User.role == role)
    if q:
        stmt = stmt.where(User.email.ilike(f"%{q}%"))
    rows = db.scalars(stmt.order_by(User.created_at.desc()).limit(200)).all()
    return [_to_out(u) for u in rows]


def _user_or_404(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


@router.post("/{user_id}/disable", response_model=Message)
def disable_user(
    user_id: uuid.UUID, admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> Message:
    user = _user_or_404(db, user_id)
    user.is_active = False
    revoke_all_refresh_tokens(db, user.id)  # a disabled account shouldn't keep a live session
    log_action(db, admin.id, "user.disable", "user", user.id)
    db.commit()
    return Message(detail="Account disabled.")


@router.post("/{user_id}/enable", response_model=Message)
def enable_user(
    user_id: uuid.UUID, admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> Message:
    user = _user_or_404(db, user_id)
    user.is_active = True
    log_action(db, admin.id, "user.enable", "user", user.id)
    db.commit()
    return Message(detail="Account re-enabled.")


@router.post("/{user_id}/reset-password", response_model=ResetPasswordOut)
def reset_password(
    user_id: uuid.UUID, admin: User = Depends(_manage), db: Session = Depends(get_db)
) -> ResetPasswordOut:
    """Generates a new temporary password and invalidates existing sessions.
    v1 has no transactional-email password-reset flow, so the admin
    communicates this value to the user out of band."""
    user = _user_or_404(db, user_id)
    temp_password = secrets.token_urlsafe(12)
    user.password_hash = hash_password(temp_password)
    revoke_all_refresh_tokens(db, user.id)
    log_action(db, admin.id, "user.reset_password", "user", user.id)
    db.commit()
    return ResetPasswordOut(temporary_password=temp_password)


# ---------------------------------------------------------------------------
# Admin accounts (superadmin only)
# ---------------------------------------------------------------------------


@router.get("/admins", response_model=list[AdminOut])
def list_admins(
    admin: User = Depends(_manage_admins), db: Session = Depends(get_db)
) -> list[AdminOut]:
    rows = db.scalars(select(User).where(User.role == UserRole.ADMIN)).all()
    return [
        AdminOut(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            admin_role=u.admin_profile.admin_role,
            is_active=u.is_active,
        )
        for u in rows
        if u.admin_profile is not None
    ]


@router.post("/admins", response_model=AdminOut, status_code=201)
def create_admin(
    body: AdminCreateIn, admin: User = Depends(_manage_admins), db: Session = Depends(get_db)
) -> AdminOut:
    user = User(
        role=UserRole.ADMIN,
        email=body.email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        is_email_verified=True,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="An account with this email already exists."
        ) from exc
    db.add(AdminProfile(user_id=user.id, admin_role=body.admin_role))
    log_action(
        db,
        admin.id,
        "admin.create",
        "user",
        user.id,
        after={"email": body.email, "admin_role": body.admin_role.value},
    )
    db.commit()
    return AdminOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        admin_role=body.admin_role,
        is_active=True,
    )
