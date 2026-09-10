"""Seed data for the `sources` registry.

One row per adapter shipped in v1. After seeding, an admin manages everything
here from the panel: enable/disable, add Greenhouse/Lever/Ashby company boards,
flip a source to the paid tier, set rate limits.

TIER / KEY POLICY (the brief's "paid tier is a config change, not a rewrite"):
    * Free, keyless sources are seeded `enabled = True`.
    * Keyed sources (Adzuna, Jooble, USAJobs) are fully implemented but seeded
      `enabled = False` with `requires_api_key = True` and `api_key_ref` set.
      Turning one on is: add the secret as a Railway variable, flip `enabled`.

PRIORITY (dedupe tie-breaker — higher wins as the canonical row):
    employer submissions .... 100  (set in code, no source row)
    ATS boards (first-party) .. 50
    aggregators .............. 10
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.enums import SourceKind, SourceTier


@dataclass(frozen=True)
class SeedSource:
    key: str
    name: str
    adapter: str
    kind: SourceKind
    enabled: bool
    tier: SourceTier = SourceTier.FREE
    priority: int = 10
    requires_api_key: bool = False
    api_key_ref: str | None = None
    base_url: str | None = None
    rate_limit_per_min: int | None = None
    refresh_interval_minutes: int = 360
    config: dict[str, Any] = field(default_factory=dict)
    note: str = ""  # not stored; explains the row for future readers


SOURCES: list[SeedSource] = [
    # =====================================================================
    # Aggregators — free, no key, enabled from day one
    # =====================================================================
    SeedSource(
        key="remotive",
        name="Remotive",
        adapter="remotive",
        kind=SourceKind.AGGREGATOR,
        enabled=True,
        priority=10,
        base_url="https://remotive.com/api/remote-jobs",
        rate_limit_per_min=20,
        refresh_interval_minutes=360,
        note="Curated remote jobs, global. Single JSON endpoint, generous but "
        "unspecified rate limit — we self-limit to be polite.",
    ),
    SeedSource(
        key="remoteok",
        name="RemoteOK",
        adapter="remoteok",
        kind=SourceKind.AGGREGATOR,
        enabled=True,
        priority=10,
        base_url="https://remoteok.com/api",
        rate_limit_per_min=10,
        refresh_interval_minutes=360,
        note="Remote jobs, global. First array element is metadata (skipped by "
        "the adapter). Requires a descriptive User-Agent.",
    ),
    SeedSource(
        key="arbeitnow",
        name="Arbeitnow",
        adapter="arbeitnow",
        kind=SourceKind.AGGREGATOR,
        enabled=True,
        priority=10,
        base_url="https://www.arbeitnow.com/api/job-board-api",
        rate_limit_per_min=30,
        refresh_interval_minutes=360,
        config={"max_pages": 10},
        note="EU-heavy plus remote. Cursor/page paginated.",
    ),
    # =====================================================================
    # ATS boards — free, no key. `config` lists the company boards to pull.
    # These lists are STARTER examples; admins curate them in the panel.
    # =====================================================================
    SeedSource(
        key="greenhouse",
        name="Greenhouse (company boards)",
        adapter="greenhouse",
        kind=SourceKind.ATS,
        enabled=True,
        priority=50,
        base_url="https://boards-api.greenhouse.io/v1/boards",
        rate_limit_per_min=50,
        refresh_interval_minutes=720,
        config={
            # board token == the slug in boards.greenhouse.io/<token>
            "board_tokens": [
                "stripe",
                "gitlab",
                "figma",
                "airbnb",
                "dropbox",
                "coinbase",
                "doordash",
                "instacart",
                "robinhood",
                "flexport",
            ]
        },
        note="Per-company boards. Public API, no key. `?content=true` returns "
        "full descriptions. One HTTP call per board.",
    ),
    SeedSource(
        key="lever",
        name="Lever (company boards)",
        adapter="lever",
        kind=SourceKind.ATS,
        enabled=True,
        priority=50,
        base_url="https://api.lever.co/v0/postings",
        rate_limit_per_min=50,
        refresh_interval_minutes=720,
        config={
            "companies": [
                "netflix",
                "plaid",
                "ramp",
                "brex",
                "notion",
                "figma",
                "attentive",
                "match",
            ]
        },
        note="Per-company postings. `?mode=json` returns structured data with "
        "categories (team/location/commitment) we map to our fields.",
    ),
    SeedSource(
        key="ashby",
        name="Ashby (company boards)",
        adapter="ashby",
        kind=SourceKind.ATS,
        enabled=True,
        priority=50,
        base_url="https://api.ashbyhq.com/posting-api/job-board",
        rate_limit_per_min=50,
        refresh_interval_minutes=720,
        config={
            "orgs": [
                "Ashby",
                "Linear",
                "Vanta",
                "Runway",
                "Posthog",
                "Hex",
                "Baseten",
            ]
        },
        note="Per-org job board API. `?includeCompensation=true` surfaces salary "
        "bands where the org publishes them.",
    ),
    # =====================================================================
    # Keyed aggregators — implemented, DISABLED until credentials are set.
    # This is the concrete form of "upgrading a source is a config change".
    # =====================================================================
    SeedSource(
        key="adzuna",
        name="Adzuna",
        adapter="adzuna",
        kind=SourceKind.AGGREGATOR,
        enabled=False,
        tier=SourceTier.FREE,  # Adzuna has a free tier; the KEY is what gates it
        priority=10,
        requires_api_key=True,
        api_key_ref="ADZUNA_APP_KEY",  # app id read from ADZUNA_APP_ID alongside
        base_url="https://api.adzuna.com/v1/api/jobs",
        rate_limit_per_min=25,
        refresh_interval_minutes=720,
        config={
            # ~20 supported country codes; start broad, trim in admin.
            "countries": ["gb", "us", "de", "fr", "nl", "ca", "au", "in", "za"],
            "results_per_page": 50,
            "max_pages": 5,
        },
        note="Multi-country. Free developer tier (app_id + app_key). Disabled "
        "until ADZUNA_APP_ID / ADZUNA_APP_KEY are provided.",
    ),
    SeedSource(
        key="jooble",
        name="Jooble",
        adapter="jooble",
        kind=SourceKind.AGGREGATOR,
        enabled=False,
        tier=SourceTier.FREE,
        priority=10,
        requires_api_key=True,
        api_key_ref="JOOBLE_API_KEY",
        base_url="https://jooble.org/api",
        rate_limit_per_min=20,
        refresh_interval_minutes=720,
        config={"keywords": ["", "remote"], "max_pages": 5},
        note="Global aggregator. POST API keyed by a path token. Disabled until "
        "JOOBLE_API_KEY is provided.",
    ),
    SeedSource(
        key="usajobs",
        name="USAJOBS (US federal)",
        adapter="usajobs",
        kind=SourceKind.AGGREGATOR,
        enabled=False,
        tier=SourceTier.FREE,
        priority=20,  # first-party government data — trust above generic aggregators
        requires_api_key=True,
        api_key_ref="USAJOBS_API_KEY",
        base_url="https://data.usajobs.gov/api/search",
        rate_limit_per_min=30,
        refresh_interval_minutes=1440,
        config={"results_per_page": 100, "max_pages": 5},
        note="US federal jobs. Needs an Authorization-Key header AND a registered "
        "User-Agent (email). Disabled until USAJOBS_API_KEY / USAJOBS_USER_AGENT set.",
    ),
]
