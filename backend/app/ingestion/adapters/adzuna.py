"""Adzuna adapter (keyed; seeded disabled until credentials are set).

API: GET https://api.adzuna.com/v1/api/jobs/{country}/search/{page}
        ?app_id={id}&app_key={key}&results_per_page=50&content-type=application/json
Shape: {"count": N, "results": [
         {id, title, description, created (ISO), redirect_url,
          company: {display_name}, location: {display_name, area: [country, region, city]},
          salary_min, salary_max, salary_is_predicted ("0"|"1"),
          contract_type ("permanent"|"contract"), contract_time ("full_time"|"part_time"),
          category: {label, tag}} ]}
Auth: app_id + app_key as query params.
      app_id  ← env ADZUNA_APP_ID     (config.api_key_ref companion)
      app_key ← env ADZUNA_APP_KEY    (config.api_key_ref)

`config.countries` is the list of ISO country codes to pull; `config.max_pages`
caps pages per country.
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
class AdzunaAdapter(SourceAdapter):
    key = "adzuna"
    kind = SourceKind.AGGREGATOR
    default_base_url = "https://api.adzuna.com/v1/api/jobs"

    def fetch(self, config: SourceConfig) -> Iterable[RawJob]:
        app_id = config.secret("ADZUNA_APP_ID")
        app_key = config.secret("ADZUNA_APP_KEY")
        if not (app_id and app_key):
            raise ValueError(
                "adzuna: ADZUNA_APP_ID / ADZUNA_APP_KEY not set — enable only "
                "after adding the credentials"
            )

        base = self.base_url(config)
        countries = config.cfg("countries") or ["gb", "us"]
        per_page = int(config.cfg("results_per_page", 50))
        max_pages = int(config.cfg("max_pages", 5))
        params_common = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": per_page,
            "content-type": "application/json",
        }

        with SourceHTTPClient(
            timeout=config.request_timeout_seconds,
            rate_limit_per_min=config.rate_limit_per_min,
        ) as http:
            for country in countries:
                for page in range(1, max_pages + 1):
                    url = f"{base}/{country}/search/{page}"
                    try:
                        payload = http.get_json(url, params=params_common)
                    except httpx.HTTPError:
                        log.warning("ingestion.adzuna.page_failed", country=country, page=page)
                        break

                    rows = payload.get("results", []) if isinstance(payload, dict) else []
                    log.info("ingestion.adzuna.page", country=country, page=page, count=len(rows))
                    if not rows:
                        break

                    for item in rows:
                        loc = item.get("location") or {}
                        area = loc.get("area") or []
                        predicted = str(item.get("salary_is_predicted")) == "1"
                        yield RawJob(
                            external_id=str(item.get("id")),
                            source_url=item.get("redirect_url"),
                            apply_url=item.get("redirect_url"),
                            title=item.get("title"),
                            company_name=(item.get("company") or {}).get("display_name"),
                            description_text=item.get("description"),
                            location_raw=loc.get("display_name"),
                            country_name=area[0] if area else None,
                            region=area[1] if len(area) > 1 else None,
                            city=area[-1] if len(area) > 2 else None,
                            # Adzuna's "predicted" salaries are model guesses, not
                            # posted figures — do not treat as disclosed.
                            salary_min=item.get("salary_min") if not predicted else None,
                            salary_max=item.get("salary_max") if not predicted else None,
                            salary_currency=_CURRENCY_BY_COUNTRY.get(country),
                            salary_period="year" if not predicted else None,
                            job_type_hint=item.get("contract_time") or item.get("contract_type"),
                            category_hint=(item.get("category") or {}).get("label"),
                            posted_at_raw=item.get("created"),
                            raw={"country": country, **item},
                        )


# Minimal country→currency map for the countries we seed; extend as needed.
_CURRENCY_BY_COUNTRY = {
    "gb": "GBP",
    "us": "USD",
    "de": "EUR",
    "fr": "EUR",
    "nl": "EUR",
    "ca": "CAD",
    "au": "AUD",
    "in": "INR",
    "za": "ZAR",
    "pl": "PLN",
    "at": "EUR",
    "br": "BRL",
    "es": "EUR",
    "it": "EUR",
    "nz": "NZD",
    "sg": "SGD",
}
