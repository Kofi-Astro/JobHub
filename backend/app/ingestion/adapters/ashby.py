"""Ashby job-board adapter (first-party company boards).

API: GET https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true
Shape: {"apiVersion": "1", "jobs": [
         {id, title, location, secondaryLocations: [...], department, team,
          isRemote (bool), descriptionHtml, descriptionPlain, publishedAt (ISO),
          employmentType ("FullTime"|"PartTime"|"Contract"|"Intern"|"Temporary"),
          address: {...}, isListed (bool), jobUrl, applyUrl,
          compensation: {compensationTierSummary, ...}} ]}
Auth: none.

`config.orgs` lists the org slugs (case-sensitive as Ashby uses them).
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

# Ashby's employmentType vocabulary → our job_type hint strings (final mapping
# to the enum still happens in normalize.py).
_EMPLOYMENT = {
    "FullTime": "full_time",
    "PartTime": "part_time",
    "Contract": "contract",
    "Intern": "internship",
    "Temporary": "temporary",
}


@register
class AshbyAdapter(SourceAdapter):
    key = "ashby"
    kind = SourceKind.ATS
    default_base_url = "https://api.ashbyhq.com/posting-api/job-board"

    def fetch(self, config: SourceConfig) -> Iterable[RawJob]:
        orgs = list(self._iter_config_list(config, "orgs", "companies"))
        if not orgs:
            raise ValueError("ashby: config.orgs is empty")

        base = self.base_url(config)
        names = config.cfg("org_names") or {}
        ok = 0
        with SourceHTTPClient(
            timeout=config.request_timeout_seconds,
            rate_limit_per_min=config.rate_limit_per_min,
        ) as http:
            for org in orgs:
                try:
                    payload = http.get_json(f"{base}/{org}?includeCompensation=true")
                except httpx.HTTPError:
                    log.warning("ingestion.ashby.org_failed", org=org)
                    continue

                rows = payload.get("jobs", []) if isinstance(payload, dict) else []
                # An unlisted board legitimately returns zero jobs; still counts
                # as a successful fetch.
                ok += 1
                log.info("ingestion.ashby.org", org=org, count=len(rows))

                for item in rows:
                    if item.get("isListed") is False:
                        continue
                    comp = item.get("compensation") or {}
                    yield RawJob(
                        external_id=str(item.get("id")),
                        source_url=item.get("jobUrl"),
                        apply_url=item.get("applyUrl") or item.get("jobUrl"),
                        title=item.get("title"),
                        company_name=names.get(org) or org,
                        description_html=item.get("descriptionHtml"),
                        description_text=item.get("descriptionPlain"),
                        location_raw=item.get("location"),
                        is_remote=bool(item.get("isRemote")),
                        job_type_hint=_EMPLOYMENT.get(item.get("employmentType")),
                        category_hint=item.get("department") or item.get("team"),
                        tags=[t for t in (item.get("department"), item.get("team")) if t],
                        salary_raw=comp.get("compensationTierSummary"),
                        posted_at_raw=item.get("publishedAt"),
                        raw={"org": org, **item},
                    )

        if ok == 0:
            raise RuntimeError("ashby: every configured org failed")
