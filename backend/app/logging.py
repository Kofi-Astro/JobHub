"""Structured logging setup.

WHAT: Configure `structlog` once, at process start, for both the API and the
worker. Local dev gets colourized key=value console output; staging/production
get single-line JSON (so Railway's log viewer and any log shipper can parse it).

WHY structlog: ingestion and the scheduler emit a lot of contextual events
("ran source=remotive created=12 expired=3"). Structured logs make those
queryable instead of being buried in free-text.
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.config import get_settings


def configure_logging() -> None:
    """Idempotently configure stdlib logging + structlog.

    Call this from the FastAPI lifespan startup and from the worker entrypoint.
    """
    settings = get_settings()
    json_logs = settings.environment in {"staging", "production"}

    # Route stdlib logging (uvicorn, sqlalchemy, apscheduler) through structlog
    # so everything shares one format.
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)

    # SQLAlchemy engine logging is very noisy at INFO; keep it at WARNING unless
    # explicitly debugging.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound logger. Prefer module-level `log = get_logger(__name__)`."""
    return structlog.get_logger(name)
