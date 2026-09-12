"""USAJOBS adapter — US federal government jobs (keyed; seeded disabled).

API: GET https://data.usajobs.gov/api/search?ResultsPerPage=100&Page=1
Headers (all required):
    Host: data.usajobs.gov
    User-Agent: <a registered email>   ← env USAJOBS_USER_AGENT
    Authorization-Key: <api key>       ← env USAJOBS_API_KEY
Shape: {"SearchResult": {
         "SearchResultCount": N, "SearchResultCountAll": M,
         "SearchResultItems": [ {"MatchedObjectId": "...",
           "MatchedObjectDescriptor": {
             PositionTitle, PositionURI, ApplyURI: [url, ...], OrganizationName,
             PositionLocation: [{LocationName, CountryCode, CountrySubDivisionCode, CityName}],
             PositionRemuneration: [{MinimumRange, MaximumRange, RateIntervalCode}],
             PositionSchedule: [{Name}], PublicationStartDate,
             UserArea: {Details: {JobSummary, ...}} }} ] }}
"""

from __future__ import annotations

from collections.abc import Iterable

from app.ingestion.base import RawJob, SourceAdapter, SourceConfig
from app.ingestion.http import SourceHTTPClient
from app.ingestion.registry import register
from app.logging import get_logger
from app.models.enums import SourceKind

log = get_logger(__name__)

# USAJOBS RateIntervalCode → our salary period vocabulary.
_RATE_INTERVAL = {
    "Per Year": "year",
    "Per Hour": "hour",
    "Per Month": "month",
    "Per Day": "day",
    "Per Week": "week",
}


@register
class USAJobsAdapter(SourceAdapter):
    key = "usajobs"
    kind = SourceKind.AGGREGATOR
    default_base_url = "https://data.usajobs.gov/api/search"

    def fetch(self, config: SourceConfig) -> Iterable[RawJob]:
        api_key = config.secret("USAJOBS_API_KEY")
        user_agent = config.secret("USAJOBS_USER_AGENT")
        if not (api_key and user_agent):
            raise ValueError("usajobs: USAJOBS_API_KEY / USAJOBS_USER_AGENT not set")

        per_page = int(config.cfg("results_per_page", 100))
        max_pages = int(config.cfg("max_pages", 5))
        headers = {
            "Host": "data.usajobs.gov",
            "User-Agent": user_agent,
            "Authorization-Key": api_key,
        }

        with SourceHTTPClient(
            timeout=config.request_timeout_seconds,
            rate_limit_per_min=config.rate_limit_per_min,
            headers=headers,
        ) as http:
            for page in range(1, max_pages + 1):
                payload = http.get_json(
                    self.base_url(config),
                    params={"ResultsPerPage": per_page, "Page": page},
                )
                items = (
                    payload.get("SearchResult", {}).get("SearchResultItems", [])
                    if isinstance(payload, dict)
                    else []
                )
                log.info("ingestion.usajobs.page", page=page, count=len(items))
                if not items:
                    break

                for wrapper in items:
                    d = wrapper.get("MatchedObjectDescriptor") or {}
                    yield self._to_raw(wrapper.get("MatchedObjectId"), d)

    @staticmethod
    def _to_raw(object_id: str | None, d: dict) -> RawJob:
        locations = d.get("PositionLocation") or []
        first_loc = locations[0] if locations else {}
        remun = (d.get("PositionRemuneration") or [{}])[0]
        schedule = (d.get("PositionSchedule") or [{}])[0].get("Name")
        apply_uris = d.get("ApplyURI") or []
        details = (d.get("UserArea") or {}).get("Details") or {}

        return RawJob(
            external_id=str(object_id or d.get("PositionID")),
            source_url=d.get("PositionURI"),
            apply_url=apply_uris[0] if apply_uris else d.get("PositionURI"),
            title=d.get("PositionTitle"),
            company_name=d.get("OrganizationName") or d.get("DepartmentName"),
            description_text=details.get("JobSummary") or d.get("QualificationSummary"),
            location_raw=first_loc.get("LocationName"),
            city=first_loc.get("CityName"),
            region=first_loc.get("CountrySubDivisionCode"),
            country_code=(first_loc.get("CountryCode") or "US")[:2].upper(),
            salary_min=_num(remun.get("MinimumRange")),
            salary_max=_num(remun.get("MaximumRange")),
            salary_currency=remun.get("CurrencyCode") or "USD",
            salary_period=_RATE_INTERVAL.get(remun.get("RateIntervalCode")),
            job_type_hint=schedule,  # "Full-time", "Part-time"
            posted_at_raw=d.get("PublicationStartDate"),
            raw=d,
        )


def _num(value: object) -> float | None:
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None
