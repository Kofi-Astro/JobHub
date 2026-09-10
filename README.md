# JobHub — Global Aggregated Job Search Platform

JobHub aggregates real job openings (full-time, part-time, contract, remote) from
many sources worldwide into one searchable, filterable platform, **and** lets
companies post listings directly. Every listing leads to a direct application
path — no subscription gates, no lead-gen middlemen.

> Full system design lives in [`ARCHITECTURE.md`](./ARCHITECTURE.md). Read that first.

---

## Tech stack

| Layer      | Choice                                                                 |
|------------|-----------------------------------------------------------------------|
| Frontend   | HTML + CSS + vanilla JavaScript (ES modules, no framework) + Tailwind |
| Backend    | Python 3.12+, FastAPI, SQLAlchemy 2.0, Pydantic v2                    |
| Database   | PostgreSQL 15+ (full-text search to start)                            |
| Background | APScheduler worker process (source refresh, staleness expiry, alerts) |
| Deploy     | Docker image, hosted on Railway (API service + worker service)        |

## Repository layout

```
JobHub/
├── ARCHITECTURE.md         # system design — data model, pipeline, decisions
├── docker-compose.yml      # local dev: postgres + api + worker
├── Dockerfile              # single production image (runs api OR worker via CMD)
├── railway.json            # Railway build/deploy config for the API service
├── Makefile                # common dev commands
├── backend/                # FastAPI application + ingestion + worker
│   ├── app/
│   │   ├── main.py         # FastAPI app factory
│   │   ├── config.py       # environment-driven settings
│   │   ├── db/             # engine, session, base
│   │   ├── models/         # SQLAlchemy ORM models (the data model)
│   │   ├── schemas/        # Pydantic request/response contracts
│   │   ├── api/routes/     # HTTP endpoints
│   │   ├── ingestion/      # source adapters + normalize + dedupe pipeline
│   │   ├── categorization/ # keyword classifier (field/sub-field)
│   │   ├── services/       # search, auth, moderation, analytics
│   │   ├── worker/         # APScheduler setup + scheduled tasks
│   │   └── seeds/          # taxonomy + source seed data
│   ├── alembic/            # database migrations
│   └── tests/
└── frontend/               # static site (served by any static host / CDN)
    ├── index.html          # search-first homepage
    ├── job.html            # job detail + apply
    ├── employer.html       # employer portal ("Post a job")
    ├── admin.html          # admin panel
    └── js/                 # ES modules: api client, components, pages, store
```

## Quick start (local, Docker)

```bash
cp .env.example .env          # adjust if you like; defaults work out of the box
make up                       # starts postgres + api + worker
make migrate                  # create database schema
make seed                     # load taxonomy + source registry
make ingest SOURCE=remotive   # pull a batch of real jobs right now
open http://localhost:8000/docs   # interactive API docs
```

Serve the frontend (it is fully static — any static server works):

```bash
make frontend-build           # compile Tailwind
make frontend-serve           # http://localhost:5173
```

## Quick start (local, no Docker)

Requires Python 3.12+ and a local PostgreSQL 15+.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg://localhost/jobhub
alembic upgrade head
python -m app.seeds.run
uvicorn app.main:app --reload
```

## Deployment (Railway)

Two services from this one repo, both using the same `Dockerfile`:

| Service | Start command                          | Purpose                              |
|---------|----------------------------------------|--------------------------------------|
| `api`   | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` | HTTP API (default `CMD`)  |
| `worker`| `python -m app.worker.run`             | APScheduler: refresh, expire, alerts |

Provision a Railway PostgreSQL plugin; it injects `DATABASE_URL`. Set the other
variables from `.env.example` in the Railway dashboard. `railway.json` configures
the API service; the worker service overrides only its start command.

See [`ARCHITECTURE.md` → Deployment](./ARCHITECTURE.md#deployment) for details.

## Testing

```bash
make test          # pytest (unit + adapter contract tests against recorded fixtures)
```
