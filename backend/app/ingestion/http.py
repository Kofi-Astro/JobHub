"""Outbound HTTP for source adapters: rate-limited, retrying, polite.

WHAT: `SourceHTTPClient` wraps `httpx.Client` with the three things every
external call to a job board needs and we do not want to re-implement per
adapter:

    1. Per-source rate limiting — a simple token bucket keyed on
       `sources.rate_limit_per_min`, so we never hammer a free API.
    2. Retry with backoff on transient failures (429, 500-599, timeouts,
       connection errors) using `tenacity`.
    3. A descriptive, honest `User-Agent` — several boards (RemoteOK, USAJOBS)
       reject or throttle blank/generic agents, and it is the courteous thing.

WHY sync: ingestion runs in the worker as a sequence of per-source jobs; there
is no benefit to async here and sync keeps adapters trivial to read and test.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app import __version__
from app.config import get_settings
from app.logging import get_logger

log = get_logger(__name__)

# Sent on every request. A real contact point is good manners and helps a source
# operator reach us instead of silently blocking.
USER_AGENT = f"JobHubBot/{__version__} (+https://jobhub.example/bot; aggregator)"


class _TokenBucket:
    """Minimal thread-safe token bucket. `rate` tokens per minute, burst = rate."""

    def __init__(self, per_minute: int) -> None:
        self.capacity = max(1, per_minute)
        self.tokens = float(self.capacity)
        self.refill_per_sec = self.capacity / 60.0
        self.updated = time.monotonic()
        self._lock = threading.Lock()

    def take(self) -> None:
        """Block until a token is available, then consume one."""
        while True:
            with self._lock:
                now = time.monotonic()
                self.tokens = min(
                    self.capacity,
                    self.tokens + (now - self.updated) * self.refill_per_sec,
                )
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                deficit = 1 - self.tokens
                wait = deficit / self.refill_per_sec
            time.sleep(min(wait, 5.0))


def _is_transient(exc: BaseException) -> bool:
    """Retryable: timeouts, connection resets, and 429/5xx responses."""
    if isinstance(exc, httpx.TimeoutException | httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


class SourceHTTPClient:
    """One instance per ingestion run (per source). Use as a context manager."""

    def __init__(
        self,
        *,
        timeout: float | None = None,
        rate_limit_per_min: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        settings = get_settings()
        self._client = httpx.Client(
            timeout=timeout or settings.http_default_timeout_seconds,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})},
            follow_redirects=True,
        )
        self._bucket = _TokenBucket(rate_limit_per_min) if rate_limit_per_min else None
        self._max_attempts = settings.http_max_retries + 1

    def __enter__(self) -> SourceHTTPClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self._client.close()

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self._request("GET", url, **kwargs).json()

    def post_json(self, url: str, **kwargs: Any) -> Any:
        return self._request("POST", url, **kwargs).json()

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._bucket:
            self._bucket.take()

        # Build the retry policy per-call so `stop_after_attempt` sees the right
        # attempt count without a class-level decorator.
        @retry(
            reraise=True,
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            retry=retry_if_exception(_is_transient),
        )
        def _do() -> httpx.Response:
            resp = self._client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp

        try:
            return _do()
        except httpx.HTTPStatusError as exc:
            log.warning(
                "ingestion.http.status_error",
                method=method,
                url=url,
                status=exc.response.status_code,
            )
            raise
        except httpx.HTTPError as exc:
            log.warning("ingestion.http.error", method=method, url=url, error=repr(exc))
            raise
