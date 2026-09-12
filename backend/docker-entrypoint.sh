#!/bin/sh
# ===========================================================================
# Container entrypoint for BOTH the API and worker services.
#
# WHY here instead of Railway's `preDeployCommand`: Railway's config-as-code
# `deploy.preDeployCommand` (see ../railway.json) is not reliably honored for
# a service whose build/start settings were first established through the
# dashboard rather than a fresh config-as-code import — ours silently never
# ran it (confirmed: no alembic output in deploy logs, and the tables did not
# exist after a "successful" deploy). Running the migration from inside the
# container itself has no such dependency on how the platform wires config —
# it works the same on Railway, in `docker run`, or under docker-compose.
#
# `alembic upgrade head` is idempotent (a no-op once already at head), so
# running it on every boot of every service (API *and* worker) is safe, not
# just tolerated — it also means a worker instance that happens to start
# before the API on a fresh environment still ends up against a migrated
# schema instead of crashing on missing tables.
#
# `set -e` + exec'ing the real command as PID 1 afterwards: a failed
# migration stops the container here (non-zero exit) rather than starting a
# process that will just 500/crash-loop against a stale schema, and `exec`
# replaces this shell so signals (SIGTERM on deploy/restart) reach uvicorn or
# the worker directly instead of being swallowed by a wrapper process.
# ===========================================================================
set -e

alembic upgrade head

exec "$@"
