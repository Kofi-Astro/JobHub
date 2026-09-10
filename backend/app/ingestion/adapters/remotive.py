"""Remotive adapter.

API: GET https://remotive.com/api/remote-jobs
Shape: {"job-count": N, "jobs": [ {...}, ... ]}  — a single response, no paging.
Auth: none.

Every Remotive job is remote, so `is_remote` is always True and
`candidate_required_location` becomes `remote_scope` ("Worldwide", "USA Only").
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
class RemotiveAdapter(SourceAdapter):
    key = "remotive"
    kind = SourceKind.AGGREGATOR
    default_base_url = "https://remotive.com/api/remote-jobs"

    def fetch(self, config: SourceConfig) -> Iterable[RawJob]:
        with SourceHTTPClient(
            timeout=config.request_timeout_seconds,
            rate_limit_per_min=config.rate_limit_per_min,
        ) as http:
            payload = http.get_json(self.base_url(config))

        jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
        log.info("ingestion.remotive.fetched", count=len(jobs))

        for item in jobs:
            # `salary` is a free-text field on Remotive ("$40k - $60k", "", …).
            yield RawJob(
                external_id=str(item.get("id")),
                source_url=item.get("url"),
                apply_url=item.get("url"),
                title=item.get("title"),
                company_name=item.get("company_name"),
                description_html=item.get("description"),
                location_raw=item.get("candidate_required_location"),
                is_remote=True,
                remote_scope=item.get("candidate_required_location"),
                salary_raw=item.get("salary") or None,
                job_type_hint=item.get("job_type"),  # "full_time", "contract", …
                category_hint=item.get("category"),
                tags=list(item.get("tags") or []),
                posted_at_raw=item.get("publication_date"),
                raw=item,
            )
