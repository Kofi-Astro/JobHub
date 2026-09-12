"""Jooble adapter (keyed; seeded disabled until credentials are set).

API: POST https://jooble.org/api/{api_key}
     body: {"keywords": "...", "location": "...", "page": "1"}
Shape: {"totalCount": N, "jobs": [
         {title, location, snippet (HTML), salary, source, type, link,
          company, updated (ISO), id} ]}
Auth: the API key is a PATH segment, not a header.

`config.keywords` is a list of query strings to sweep (use "" for everything +
"remote" for remote-focused). `config.max_pages` caps pages per keyword.
Jooble does not expose structured location, so `location` stays raw for the
normalizer to parse.
"""

from __future__ import annotations

from collections.abc import Iterable

import httpx

from app.ingestion.base import RawJob, SourceAdapter, SourceConfig
from app.ingestion.http import SourceHTTPClient
from app.ingestion.registry import register
from app.logging import get_logger
from app.models.enums import SourceKind

log = get_logger(__name__)


@register
class JoobleAdapter(SourceAdapter):
    key = "jooble"
    kind = SourceKind.AGGREGATOR
    default_base_url = "https://jooble.org/api"

    def fetch(self, config: SourceConfig) -> Iterable[RawJob]:
        api_key = config.secret("JOOBLE_API_KEY")
        if not api_key:
            raise ValueError("jooble: JOOBLE_API_KEY not set")

        url = f"{self.base_url(config)}/{api_key}"
        keywords = config.cfg("keywords") or [""]
        max_pages = int(config.cfg("max_pages", 5))

        with SourceHTTPClient(
            timeout=config.request_timeout_seconds,
            rate_limit_per_min=config.rate_limit_per_min,
        ) as http:
            for kw in keywords:
                for page in range(1, max_pages + 1):
                    body = {"keywords": kw, "page": str(page)}
                    try:
                        payload = http.post_json(url, json=body)
                    except httpx.HTTPError:
                        log.warning("ingestion.jooble.page_failed", keyword=kw, page=page)
                        break

                    rows = payload.get("jobs", []) if isinstance(payload, dict) else []
                    log.info("ingestion.jooble.page", keyword=kw, page=page, count=len(rows))
                    if not rows:
                        break

                    for item in rows:
                        loc = item.get("location") or ""
                        yield RawJob(
                            external_id=str(item.get("id")),
                            source_url=item.get("link"),
                            apply_url=item.get("link"),
                            title=item.get("title"),
                            company_name=item.get("company") or None,
                            description_html=item.get("snippet"),
                            location_raw=loc or None,
                            is_remote="remote" in f"{item.get('title', '')} {loc}".lower() or None,
                            salary_raw=item.get("salary") or None,
                            job_type_hint=item.get("type"),
                            posted_at_raw=item.get("updated"),
                            raw={"keyword": kw, **item},
                        )
