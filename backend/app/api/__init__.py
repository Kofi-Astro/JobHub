"""HTTP API package.

`api/routes/*` holds one router module per resource area. `api/deps.py` holds
shared FastAPI dependencies (DB session, current user, pagination). Routers are
assembled into the app in `app.main.create_app`.
"""
