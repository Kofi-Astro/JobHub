"""Background worker package.

Runs as its own process (`python -m app.worker.run`), separate from the API, so
scheduled work cannot slow down request handling and can be scaled/restarted
independently.

    run.py         entrypoint — boots the APScheduler event loop
    scheduler.py    wires tasks.py's functions onto their intervals
    tasks.py        the actual jobs: source dispatch, staleness expiry, alerts
"""
