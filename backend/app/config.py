"""Application configuration.

WHAT: A single `Settings` object, populated from environment variables (and a
local `.env` file), used everywhere instead of reading `os.environ` ad hoc.

WHY: 12-factor config. Behaviour differs between local/staging/production only by
environment, never by code branches or committed config files. Pydantic gives us
validation and typing for free — a missing `JWT_SECRET` fails fast at startup
with a clear message instead of surfacing as a confusing 500 later.
"""

from __future__ import annotations

import functools

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # `.env` is read for local dev; in production the process environment
    # (Railway variables) takes precedence. Unknown keys are ignored so the
    # shared `.env` can hold frontend-only vars too.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Core --------------------------------------------------------------
    environment: str = Field(default="local")  # local | staging | production

    # Raw database URL as provided by the platform. Railway's Postgres plugin
    # injects `postgresql://user:pass@host:port/db`; SQLAlchemy 2.0 + psycopg 3
    # wants the `postgresql+psycopg://` scheme. `database_url` (below) normalizes.
    database_url_raw: str = Field(alias="DATABASE_URL")

    cors_allow_origins: str = Field(
        default="http://localhost:5173,http://localhost:8000",
        alias="CORS_ALLOW_ORIGINS",
    )

    # --- Auth ------------------------------------------------------------------
    jwt_secret: str = Field(alias="JWT_SECRET")
    jwt_access_ttl_minutes: int = Field(default=15, alias="JWT_ACCESS_TTL_MINUTES")
    jwt_refresh_ttl_days: int = Field(default=30, alias="JWT_REFRESH_TTL_DAYS")

    # --- Ingestion / HTTP ------------------------------------------------------
    http_default_timeout_seconds: float = Field(default=30.0, alias="HTTP_DEFAULT_TIMEOUT_SECONDS")
    http_max_retries: int = Field(default=3, alias="HTTP_MAX_RETRIES")

    # Keyed adapter credentials. Blank ⇒ that source stays disabled. Adapters
    # look these up by the name stored in `sources.api_key_ref`, via
    # `resolve_api_key()` below — they never read the environment directly.
    adzuna_app_id: str = Field(default="", alias="ADZUNA_APP_ID")
    adzuna_app_key: str = Field(default="", alias="ADZUNA_APP_KEY")
    jooble_api_key: str = Field(default="", alias="JOOBLE_API_KEY")
    usajobs_api_key: str = Field(default="", alias="USAJOBS_API_KEY")
    usajobs_user_agent: str = Field(default="", alias="USAJOBS_USER_AGENT")

    # --- Email ---------------------------------------------------------------
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="JobHub <no-reply@jobhub.example>", alias="SMTP_FROM")

    # --- Worker --------------------------------------------------------------
    stale_job_expiry_days: int = Field(default=14, alias="STALE_JOB_EXPIRY_DAYS")

    # ---------------------------------------------------------------------------
    # Derived / validated values
    # ---------------------------------------------------------------------------

    @field_validator("environment")
    @classmethod
    def _known_environment(cls, v: str) -> str:
        allowed = {"local", "staging", "production", "test"}
        if v not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {sorted(allowed)}, got {v!r}")
        return v

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """SQLAlchemy-ready URL.

        Normalizes the platform-provided value so both `postgres://` (legacy
        Heroku/Railway style) and `postgresql://` map to the psycopg-3 driver.
        """
        url = self.database_url_raw
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins(self) -> list[str]:
        """CORS origins as a list (env var is comma-separated for portability)."""
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def smtp_enabled(self) -> bool:
        """When False, outbound email is logged instead of sent (local dev)."""
        return bool(self.smtp_host)

    def resolve_api_key(self, ref: str | None) -> str | None:
        """Return the secret named by `sources.api_key_ref`, or None if unset.

        WHY indirection: the `sources` table stores only the *name* of the
        credential (e.g. "ADZUNA_APP_KEY"), never the value. This keeps secrets
        out of the database and lets an admin wire up a paid source by adding a
        Railway variable — no code, no DB secret.
        """
        if not ref:
            return None
        mapping = {
            "ADZUNA_APP_ID": self.adzuna_app_id,
            "ADZUNA_APP_KEY": self.adzuna_app_key,
            "JOOBLE_API_KEY": self.jooble_api_key,
            "USAJOBS_API_KEY": self.usajobs_api_key,
            "USAJOBS_USER_AGENT": self.usajobs_user_agent,
        }
        return mapping.get(ref) or None


@functools.lru_cache
def get_settings() -> Settings:
    """Cached accessor.

    `lru_cache` makes this an effective singleton: the environment is read and
    validated exactly once per process. Tests override by clearing the cache
    (`get_settings.cache_clear()`) after patching the environment.
    """
    return Settings()  # type: ignore[call-arg]  # values come from the environment
