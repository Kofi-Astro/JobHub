# ===========================================================================
# Single production image for BOTH the API service and the worker service.
#
# Which one runs is decided by the start command:
#   api    → uvicorn app.main:app --host 0.0.0.0 --port $PORT   (default CMD)
#   worker → python -m app.worker.run                            (Railway override)
#
# Python is pinned to 3.12 for wheel stability across all our dependencies,
# independent of whatever version a developer has locally.
# ===========================================================================

FROM python:3.12-slim AS base

# - PYTHONDONTWRITEBYTECODE: no .pyc clutter in the layer
# - PYTHONUNBUFFERED: logs stream immediately (important for Railway log capture)
# - PIP_NO_CACHE_DIR: smaller image
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libpq is needed at runtime by psycopg; build-essential only during pip install
# of any sdist-only deps, then removed to keep the image lean.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependency layer first so code changes don't bust the pip cache.
# INSTALL_DEV=true (set by docker-compose for local work) additionally installs
# pytest/ruff/respx. Railway builds leave it false → lean runtime image.
ARG INSTALL_DEV=false
COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN pip install -r requirements.txt \
    && if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.txt; fi

# Application code.
COPY backend/ ./

# Non-root runtime user.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Documented port for local `docker run`; Railway provides $PORT at runtime.
EXPOSE 8000

# Container-level healthcheck (Railway also has its own HTTP healthcheck).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-8000}/api/health" || exit 1

# Default = API. The worker service overrides this in railway.json / compose.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
