"""Background worker package.

Runs as its own process (`python -m app.worker.run`), separate from the API, so
scheduled work cannot slow down request handling and can be scaled/restarted
independently. Fleshed out in milestone 12; `run.py` here is the entrypoint.
"""
