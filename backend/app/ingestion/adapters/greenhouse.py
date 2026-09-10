"""Greenhouse job-board adapter (first-party company boards).

API: GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
Shape: {"jobs": [ {id, title, absolute_url, updated_at, location: {name},
        content (HTML, entity-encoded), metadata: [...], departments: [...],
        offices: [...] } ], "meta": {"total": N}}
Auth: none.

One `sources` row drives MANY boards: `config.board_tokens` is the list of
company slugs. Each board is one HTTP call. A single board failing is logged and
skipped (partial run); a total failure raises.
"""

from __future__ import annotations

import html
from collections.abc import Iterable

import httpx

from app.ingestion.base import RawJob, SourceAdapter, SourceConfig
from app.ingestion.http import SourceHTTPClient
from app.ingestion.registry import register
from app.logging import get_logger
from app.models.enums import SourceKind

log = get_logger(__name__)


@register
class GreenhouseAdapter(SourceAdapter):
    key = "greenhouse"
    kind = SourceKind.ATS
    default_base_url = "https://boards-api.greenhouse.io/v1/boards"

    def fetch(self, config: SourceConfig) -> Iterable[RawJob]:
        tokens = list(self._iter_config_list(config, "board_tokens", "boards"))
        if not tokens:
            raise ValueError("greenhouse: config.board_tokens is empty")

        base = self.base_url(config)
        ok_boards = 0
        with SourceHTTPClient(
            timeout=config.request_timeout_seconds,
            rate_limit_per_min=config.rate_limit_per_min,
        ) as http:
            for token in tokens:
                url = f"{base}/{token}/jobs?content=true"
                try:
                    payload = http.get_json(url)
                except httpx.HTTPError:
                    # One dead board must not sink the whole source.
                    log.warning("ingestion.greenhouse.board_failed", board=token)
                    continue

                rows = payload.get("jobs", []) if isinstance(payload, dict) else []
                ok_boards += 1
                log.info("ingestion.greenhouse.board", board=token, count=len(rows))

                for item in rows:
                    loc = (item.get("location") or {}).get("name")
                    departments = [d.get("name") for d in item.get("departments") or []]
                    yield RawJob(
                        external_id=str(item.get("id")),
                        source_url=item.get("absolute_url"),
                        apply_url=item.get("absolute_url"),
                        title=item.get("title"),
                        company_name=self._company_name(config, token, item),
                        # Greenhouse HTML-entity-encodes the `content` field.
                        description_html=html.unescape(item.get("content") or ""),
                        location_raw=loc,
                        category_hint=departments[0] if departments else None,
                        tags=[d for d in departments if d],
                        posted_at_raw=item.get("updated_at") or item.get("first_published"),
                        raw={"board_token": token, **item},
                    )

        if ok_boards == 0:
            raise RuntimeError("greenhouse: every configured board failed")

    @staticmethod
    def _company_name(config: SourceConfig, token: str, item: dict) -> str:
        """Greenhouse job payloads don't carry the company name; derive it.

        `config.board_names` may map token → display name; otherwise title-case
        the token ("flexport" → "Flexport").
        """
        mapping = config.cfg("board_names") or {}
        return mapping.get(token) or token.replace("-", " ").title()
