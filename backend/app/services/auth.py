"""Authentication primitives: password hashing, JWT access tokens, and
opaque rotating refresh tokens.

DESIGN:
    * Passwords are hashed with argon2id (via `argon2-cffi`) — the current
      OWASP-recommended default, memory-hard against GPU cracking.
    * Access tokens are short-lived (15 min) signed JWTs (HS256) carrying just
      `sub` (user id) and `role`. Short life bounds the damage of a leaked
      token; the frontend silently refreshes via the refresh token.
    * Refresh tokens are OPAQUE random strings, not JWTs. Only their SHA-256
      hash is stored (`RefreshToken.token_hash`), so a database leak does not
      hand out usable tokens. They are long-lived (30 days), rotated on every
      use (old one revoked, new one issued), and revocable individually or
      all-at-once ("log out everywhere") — none of which a stateless JWT
      refresh token could do without a server-side blocklist anyway.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import RefreshToken, User
from app.models.enums import UserRole

_hasher = PasswordHasher()

# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(raw: str, hashed: str | None) -> bool:
    """True if `raw` matches `hashed`. False (never raises) for any mismatch,
    malformed hash, or a user with no password set (OAuth-only account)."""
    if not hashed:
        return False
    try:
        return _hasher.verify(hashed, raw)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Access tokens (JWT)
# ---------------------------------------------------------------------------

JWT_ALGORITHM = "HS256"


def create_access_token(user: User) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    settings = get_settings()
    ttl = timedelta(minutes=settings.jwt_access_ttl_minutes)
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "iat": now,
        "exp": now + ttl,
        "type": "access",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)
    return token, int(ttl.total_seconds())


class InvalidToken(Exception):
    """Raised for any access-token problem — expired, malformed, wrong type."""


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc
    if payload.get("type") != "access":
        raise InvalidToken("wrong token type")
    return payload


# ---------------------------------------------------------------------------
# Refresh tokens (opaque, DB-backed, rotating)
# ---------------------------------------------------------------------------


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_refresh_token(
    db: Session,
    user: User,
    *,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[str, RefreshToken]:
    """Create and persist a new refresh token; returns the RAW value (only
    time it is ever available in full) and its row."""
    settings = get_settings()
    raw = secrets.token_urlsafe(48)
    row = RefreshToken(
        user_id=user.id,
        token_hash=_hash_token(raw),
        expires_at=datetime.now(UTC) + timedelta(days=settings.jwt_refresh_ttl_days),
        user_agent=(user_agent or "")[:400] or None,
        ip=ip,
    )
    db.add(row)
    db.flush()
    return raw, row


class RefreshTokenInvalid(Exception):
    """Raised when a presented refresh token is missing, expired, or revoked."""


def rotate_refresh_token(
    db: Session,
    raw_token: str,
    *,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[User, str]:
    """Validate `raw_token`, revoke it, and issue a replacement.

    Rotation means a stolen-and-reused refresh token is detected the moment
    the legitimate client tries to use its (now-revoked) copy — at which point
    an admin/observability hook could revoke the whole family. v1 logs it; a
    fuller "reuse detection" response is a later hardening pass.
    """
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash_token(raw_token)))
    now = datetime.now(UTC)
    if row is None or row.revoked_at is not None or row.expires_at < now:
        raise RefreshTokenInvalid("refresh token is invalid, expired, or revoked")

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise RefreshTokenInvalid("account is inactive")

    row.revoked_at = now
    new_raw, _ = issue_refresh_token(db, user, user_agent=user_agent, ip=ip)
    return user, new_raw


def revoke_refresh_token(db: Session, raw_token: str) -> None:
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash_token(raw_token)))
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)


def revoke_all_refresh_tokens(db: Session, user_id: uuid.UUID) -> int:
    """ "Log out everywhere". Returns the number of sessions revoked."""
    now = datetime.now(UTC)
    rows = list(
        db.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
            )
        )
    )
    for row in rows:
        row.revoked_at = now
    return len(rows)


# ---------------------------------------------------------------------------
# Small helper the routes use to keep role checks obvious at the call site
# ---------------------------------------------------------------------------


def is_role(user: User, *roles: UserRole) -> bool:
    return user.role in roles
