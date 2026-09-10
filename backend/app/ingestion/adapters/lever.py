"""Lever postings adapter (first-party company boards).

API: GET https://api.lever.co/v0/postings/{company}?mode=json
Shape: a JSON ARRAY of postings:
       {id, text (title), hostedUrl, applyUrl, createdAt (ms epoch),
        workplaceType ("remote"|"hybrid"|"on-site"),
        categories: {commitment, location, team, department},
        description (HTML), descriptionPlain, lists: [{text, content}], ...}
Auth: none.

`config.companies` lists the company slugs. `workplaceType` maps cleanly to our
`workplace_type`; `categories.commitment` ("Full-time") to `job_type`;
`categories.team`/`department` is the categorization hint.
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
class LeverAdapter(SourceAdapter):
    key = "lever"
    kind = SourceKind.ATS
    default_base_url = "https://api.lever.co/v0/postings"

    def fetch(self, config: SourceConfig) -> Iterable[RawJob]:
        companies = list(self._iter_config_list(config, "companies", "sites"))
        if not companies:
            raise ValueError("lever: config.companies is empty")

        base = self.base_url(config)
        names = config.cfg("company_names") or {}
        ok = 0
        with SourceHTTPClient(
            timeout=config.request_timeout_seconds,
            rate_limit_per_min=config.rate_limit_per_min,
        ) as http:
            for slug in companies:
                try:
                    rows = http.get_json(f"{base}/{slug}?mode=json")
                except httpx.HTTPError:
                    log.warning("ingestion.lever.company_failed", company=slug)
                    continue
                if not isinstance(rows, list):
                    continue
                ok += 1
                log.info("ingestion.lever.company", company=slug, count=len(rows))

                for item in rows:
                    cats = item.get("categories") or {}
                    yield RawJob(
                        external_id=str(item.get("id")),
                        source_url=item.get("hostedUrl"),
                        apply_url=item.get("applyUrl") or item.get("hostedUrl"),
                        title=item.get("text"),
                        company_name=names.get(slug) or slug.replace("-", " ").title(),
                        description_html=item.get("description"),
                        description_text=item.get("descriptionPlain"),
                        location_raw=cats.get("location"),
                        workplace_hint=item.get("workplaceType"),
                        is_remote=(item.get("workplaceType") == "remote") or None,
                        job_type_hint=cats.get("commitment"),  # "Full-time"
                        category_hint=cats.get("team") or cats.get("department"),
                        tags=[c for c in (cats.get("team"), cats.get("department")) if c],
                        posted_at_raw=str(item.get("createdAt")),  # ms epoch
                        raw={"company": slug, **item},
                    )

        if ok == 0:
            raise RuntimeError("lever: every configured company failed")
