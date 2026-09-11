"""Shared FastAPI dependencies: pagination, the anonymous session id, and the
auth/role guards every protected route composes from.

Auth model: the access token is a short-lived JWT sent as
`Authorization: Bearer <token>`. `get_current_user` decodes it and loads the
`User` row; `require_user` / `require_role` build on it to 401/403 as
appropriate. Nothing here touches the refresh token — that is only ever read
from its httpOnly cookie, inside `routes/auth.py`, never as a general dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.models.enums import UserRole
from app.services.auth import InvalidToken, decode_access_token

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


@dataclass(slots=True)
class Pagination:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def pagination(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> Pagination:
    return Pagination(page=page, page_size=page_size)


def session_id(x_session_id: str | None = Header(default=None)) -> str | None:
    """The client-generated UUID (stored in localStorage) that ties an anonymous
    visitor's analytics events together. Never required."""
    if not x_session_id:
        return None
    return x_session_id[:64]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

# `auto_error=False`: a missing header should mean "anonymous", not a 403 from
# the security scheme itself — routes that require auth raise their own 401.
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User | None:
    """The logged-in user, or None for an anonymous request. Never raises —
    an invalid/expired token is treated the same as no token, so a stale
    token in a browser tab degrades to "logged out" rather than a hard error."""
    if creds is None:
        return None
    try:
        payload = decode_access_token(creds.credentials)
    except InvalidToken:
        return None
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        return None
    return user


def require_user(user: User | None = Depends(get_current_user)) -> User:
    """401 if no valid session. Use for any endpoint that needs *a* logged-in
    user, regardless of role (e.g. GET /api/auth/me)."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def require_role(*roles: UserRole):
    """Dependency factory: 401 if not logged in, 403 if the wrong role.

    Usage: `user: User = Depends(require_role(UserRole.EMPLOYER))`.
    """

    def _dep(user: User = Depends(require_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Not authorized for this action.")
        return user

    return _dep
