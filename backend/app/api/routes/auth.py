"""Authentication: register (seeker / employer), login, refresh, logout, me.

Token transport:
    * access token  → JSON body, held in memory by the frontend, sent as
                      `Authorization: Bearer <token>`.
    * refresh token → httpOnly, `SameSite=Lax` cookie scoped to `/api/auth`,
                      never readable by JavaScript (mitigates XSS token theft)
                      and never sent to unrelated routes.

There is no admin registration endpoint — admin accounts are provisioned via
`python -m app.seeds.create_admin` (an operator action), never self-serve.
"""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.config import get_settings
from app.db import get_db
from app.models import EmployerProfile, User
from app.models.enums import (
    AnalyticsEventType,
    EmployerAccountStatus,
    UserRole,
)
from app.schemas.auth import (
    EmployerProfileOut,
    LoginIn,
    MeOut,
    RegisterEmployerIn,
    RegisterSeekerIn,
    TokenOut,
    UserOut,
)
from app.schemas.common import Message
from app.services.analytics import record_event
from app.services.auth import (
    RefreshTokenInvalid,
    create_access_token,
    hash_password,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_password,
)
from app.services.companies import resolve_company

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
REFRESH_COOKIE_PATH = "/api/auth"


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        raw_token,
        max_age=settings.jwt_refresh_ttl_days * 86400,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


def _client_ip(request: Request) -> str | None:
    """`request.client.host`, but only if it is actually an IP address.

    Behind some proxies (and always in tests) that field can hold a hostname
    ("testclient", a unix-socket peer name, …) which the `ip` column (Postgres
    `INET`) rejects — this is informational-only data, so silently drop
    anything that isn't a real IP rather than failing the request over it.
    """
    host = request.client.host if request.client else None
    if not host:
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return None
    return host


def _issue_tokens(db: Session, user: User, request: Request, response: Response) -> TokenOut:
    access, expires_in = create_access_token(user)
    raw_refresh, _ = issue_refresh_token(
        db,
        user,
        user_agent=request.headers.get("user-agent"),
        ip=_client_ip(request),
    )
    _set_refresh_cookie(response, raw_refresh)
    return TokenOut(access_token=access, expires_in=expires_in, user=UserOut.model_validate(user))


@router.post("/register/seeker", response_model=TokenOut, status_code=201)
def register_seeker(
    body: RegisterSeekerIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenOut:
    user = User(
        role=UserRole.SEEKER,
        email=body.email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="An account with this email already exists."
        ) from exc

    record_event(db, AnalyticsEventType.SEEKER_SIGNUP, user_id=user.id)
    return _issue_tokens(db, user, request, response)


@router.post("/register/employer", response_model=TokenOut, status_code=201)
def register_employer(
    body: RegisterEmployerIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenOut:
    user = User(
        role=UserRole.EMPLOYER,
        email=body.email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
    )
    db.add(user)
    try:
        db.flush()  # need user.id for the profile FK, before the company insert races anything
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="An account with this email already exists."
        ) from exc

    company = resolve_company(db, body.company_name, website=body.company_website)
    if company is None:
        # resolve_company only returns None for placeholder/empty names, which
        # the schema already rejects (min_length=1) — defensive, not expected.
        raise HTTPException(status_code=422, detail="A valid company name is required.")

    db.add(
        EmployerProfile(
            user_id=user.id,
            company_id=company.id,
            job_title=body.job_title,
            phone=body.phone,
            # New employer accounts are flagged for admin approval before
            # going live (brief) — they can sign in, but posting is gated on
            # this status until milestone 10's moderation queue approves it.
            account_status=EmployerAccountStatus.PENDING,
        )
    )
    db.commit()

    record_event(
        db,
        AnalyticsEventType.EMPLOYER_SIGNUP,
        user_id=user.id,
        properties={"company": company.name},
    )
    return _issue_tokens(db, user, request, response)


@router.post("/login", response_model=TokenOut)
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenOut:
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        # Identical message for "no such user" and "wrong password" — do not
        # let the error tell an attacker which one it was.
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been disabled.")
    if (
        user.employer_profile
        and user.employer_profile.account_status == EmployerAccountStatus.SUSPENDED
    ):
        raise HTTPException(status_code=403, detail="This employer account has been suspended.")

    user.last_login_at = datetime.now(UTC)
    db.commit()
    return _issue_tokens(db, user, request, response)


@router.post("/refresh", response_model=TokenOut)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)) -> TokenOut:
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="No refresh token presented.")
    try:
        user, new_raw = rotate_refresh_token(
            db,
            raw,
            user_agent=request.headers.get("user-agent"),
            ip=_client_ip(request),
        )
    except RefreshTokenInvalid as exc:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=401, detail="Session expired. Please log in again."
        ) from exc

    db.commit()
    access, expires_in = create_access_token(user)
    _set_refresh_cookie(response, new_raw)
    return TokenOut(access_token=access, expires_in=expires_in, user=UserOut.model_validate(user))


@router.post("/logout", response_model=Message)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Message:
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        revoke_refresh_token(db, raw)
        db.commit()
    _clear_refresh_cookie(response)
    return Message(detail="Logged out.")


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(require_user)) -> MeOut:
    out = MeOut.model_validate(user)
    if user.admin_profile:
        out.admin_role = user.admin_profile.admin_role
    if user.employer_profile:
        profile = user.employer_profile
        out.employer = EmployerProfileOut(
            company_id=profile.company_id,
            company_name=profile.company.name if profile.company else "",
            account_status=profile.account_status,
            posting_quota=profile.posting_quota,
            plan=profile.plan,
        )
    return out
