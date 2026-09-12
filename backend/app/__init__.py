"""JobHub backend application package.

Sub-packages:
    config          environment-driven settings (12-factor)
    db              SQLAlchemy engine / session / declarative base
    models          ORM models — the data model of record
    schemas         Pydantic request/response contracts
    api             FastAPI routers (the HTTP surface)
    ingestion       source adapters + normalize/dedupe pipeline
    categorization  keyword field/sub-field classifier
    services        cross-cutting logic (search, auth, moderation, analytics)
    worker          APScheduler process (source refresh, expiry, alerts)
    seeds           taxonomy + source-registry seed data
"""

__version__ = "0.1.0"
