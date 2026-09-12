"""RemoteOK adapter.

API: GET https://remoteok.com/api
Shape: a JSON ARRAY. Element 0 is a legal/metadata object
       ({"legal": "..."}) and is skipped; the rest are jobs.
Auth: none, but a descriptive User-Agent is required (blank/generic ones are
      blocked). `SourceHTTPClient` always sends one.

All RemoteOK jobs are remote.
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
class RemoteOKAdapter(SourceAdapter):
    key = "remoteok"
    kind = SourceKind.AGGREGATOR
    default_base_url = "https://remoteok.com/api"

    def fetch(self, config: SourceConfig) -> Iterable[RawJob]:
        with SourceHTTPClient(
            timeout=config.request_timeout_seconds,
            rate_limit_per_min=config.rate_limit_per_min,
        ) as http:
            payload = http.get_json(self.base_url(config))

        if not isinstance(payload, list):
            raise ValueError("RemoteOK: expected a JSON array")

        # Skip the leading metadata/legal object — real jobs have a "position".
        items = [it for it in payload if isinstance(it, dict) and it.get("position")]
        log.info("ingestion.remoteok.fetched", count=len(items))

        for item in items:
            # RemoteOK provides numeric salary_min/salary_max when known.
            yield RawJob(
                external_id=str(item.get("id") or item.get("slug")),
                source_url=item.get("url"),
                apply_url=item.get("apply_url") or item.get("url"),
                title=item.get("position"),
                company_name=item.get("company"),
                description_html=item.get("description"),
                location_raw=item.get("location") or "Remote",
                is_remote=True,
                remote_scope=item.get("location") or None,
                salary_min=_to_float(item.get("salary_min")),
                salary_max=_to_float(item.get("salary_max")),
                salary_currency="USD" if item.get("salary_min") else None,
                salary_period="year" if item.get("salary_min") else None,
                tags=list(item.get("tags") or []),
                posted_at_raw=item.get("date"),  # ISO 8601 string
                raw=item,
            )


def _to_float(value: object) -> float | None:
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None
