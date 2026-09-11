"""FastAPI application factory.

WHAT: `create_app()` builds and returns the ASGI app — middleware, exception
handlers, and all routers. `app` at module level is what uvicorn imports
(`uvicorn app.main:app`).

WHY a factory: tests build a fresh app with overridden settings/DB; nothing
important happens at import time.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.config import get_settings
from app.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Startup/shutdown hook.

    Kept deliberately thin: logging config, and a one-line "up" log. The DB
    schema is managed by Alembic (never `create_all` at boot), and the scheduler
    lives in a *separate* process (`app.worker.run`), so there is nothing else to
    start here.
    """
    configure_logging()
    settings = get_settings()
    log.info("api.startup", version=__version__, environment=settings.environment)
    yield
    log.info("api.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="JobHub API",
        version=__version__,
        summary="Aggregated global job search + direct employer postings.",
        # Interactive docs are useful in every environment except production,
        # where we don't want to advertise the full surface publicly.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )

    # --- CORS ------------------------------------------------------------------
    # The frontend is served from a different origin (static host / CDN), so the
    # browser needs explicit permission to call the API. Origins are configured
    # per environment; credentials are allowed for the refresh-token cookie.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Total-Count"],  # pagination total for list endpoints
    )

    # --- Exception handling --------------------------------------------------
    # Convert uncaught exceptions into a consistent JSON envelope and log them
    # with request context, instead of leaking a stack trace to the client.
    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error(
            "api.unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=repr(exc),
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error."},
        )

    # --- Routers ------------------------------------------------------------
    # Each milestone registers its router here. Order is cosmetic (docs grouping).
    from app.api.routes import auth, jobs, meta, taxonomy

    app.include_router(meta.router)
    app.include_router(taxonomy.router)
    app.include_router(jobs.router)
    app.include_router(auth.router)

    return app


# The ASGI entrypoint uvicorn / gunicorn import.
app = create_app()
