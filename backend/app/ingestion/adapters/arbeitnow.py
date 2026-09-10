"""Arbeitnow adapter.

API: GET https://www.arbeitnow.com/api/job-board-api
Shape: {"data": [ {...} ], "links": {"next": url|null}, "meta": {...}}
Auth: none. Paginated via `?page=N`; we follow `links.next` up to
      `config.max_pages` (default 10).

Arbeitnow is EU-heavy but includes remote roles worldwide. `remote` is a real
boolean on each record; `job_types` is a list of source-vocab strings.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.ingestion.base import RawJob, SourceAdapter, SourceConfig
from app.ingestion.http import SourceHTTPClient
from app.ingestion.registry import register
from app.logging import get_logger
from app.models.enums import SourceKind

log = get_logger(__name__)


@register
class ArbeitnowAdapter(SourceAdapter):
    key = "arbeitnow"
    kind = SourceKind.AGGREGATOR
    default_base_url = "https://www.arbeitnow.com/api/job-board-api"

    def fetch(self, config: SourceConfig) -> Iterable[RawJob]:
        max_pages = int(config.cfg("max_pages", 10))
        url: str | None = self.base_url(config)
        seen_pages = 0

        with SourceHTTPClient(
            timeout=config.request_timeout_seconds,
            rate_limit_per_min=config.rate_limit_per_min,
        ) as http:
            while url and seen_pages < max_pages:
                payload = http.get_json(url)
                rows = payload.get("data", []) if isinstance(payload, dict) else []
                seen_pages += 1
                log.info("ingestion.arbeitnow.page", page=seen_pages, count=len(rows))

                for item in rows:
                    job_types = item.get("job_types") or []
                    yield RawJob(
                        external_id=item.get("slug"),
                        source_url=item.get("url"),
                        apply_url=item.get("url"),
                        title=item.get("title"),
                        company_name=item.get("company_name"),
                        description_html=item.get("description"),
                        location_raw=item.get("location"),
                        is_remote=bool(item.get("remote")),
                        job_type_hint=job_types[0] if job_types else None,
                        tags=list(item.get("tags") or []),
                        posted_at_raw=str(item.get("created_at")),  # unix epoch
                        raw=item,
                    )

                # Advance to the next page if the API says there is one.
                url = (
                    (payload.get("links") or {}).get("next") if isinstance(payload, dict) else None
                )
