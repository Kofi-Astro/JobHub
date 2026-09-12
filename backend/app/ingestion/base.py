"""The source-adapter contract.

Three things live here:

    RawJob        — the permissive, mostly-unparsed shape an adapter emits.
    SourceConfig  — a frozen snapshot of a `sources` row + resolved secrets,
                    handed to the adapter. Adapters never touch the ORM.
    SourceAdapter — the ABC every adapter implements: `fetch(config) -> RawJob…`

WHY this split: an adapter's *only* job is "talk to one external API and map its
field names onto RawJob field names". Everything hard and shared — HTML
sanitising, location parsing, salary parsing, enum mapping, dedupe, categorising,
upserting — happens once, downstream, in the pipeline. New sources stay tiny and
uniform, and every adapter is testable against a recorded JSON fixture with no
network and no database.
"""

from __future__ import annotations

import abc
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.models.enums import SourceKind


@dataclass(slots=True)
class RawJob:
    """One job as pulled from a source, before normalization.

    Every field is optional and only lightly typed on purpose. An adapter should
    populate whatever the source provides and leave the rest as ``None`` — it
    must NOT guess, clean, or infer (that is the normalizer's job, where the
    logic is shared and tested). The two things an adapter *should* always try to
    provide are `external_id` and one of `apply_url` / `source_url`.
    """

    # --- Identity ---
    external_id: str | None = None
    source_url: str | None = None
    apply_url: str | None = None
    apply_email: str | None = None

    # --- Content ---
    title: str | None = None
    company_name: str | None = None
    description_html: str | None = None
    description_text: str | None = None  # set only if the source gives plaintext

    # --- Location (raw strings / hints; parsing happens later) ---
    location_raw: str | None = None
    city: str | None = None
    region: str | None = None
    country_code: str | None = None
    country_name: str | None = None
    is_remote: bool | None = None
    remote_scope: str | None = None
    workplace_hint: str | None = None  # e.g. "hybrid", "on-site" verbatim

    # --- Compensation (raw; parsed later) ---
    salary_raw: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None  # "year" / "hour" / verbatim source term

    # --- Classification hints (mapped to our enums later) ---
    job_type_hint: str | None = None
    experience_hint: str | None = None
    category_hint: str | None = None  # source's own category label, if any
    tags: list[str] = field(default_factory=list)

    # --- Dates (raw; parsed leniently later) ---
    posted_at_raw: str | None = None

    # --- Provenance ---
    # The untouched source record — persisted to `jobs.raw` so normalization and
    # categorization can be re-run later without re-fetching.
    raw: dict[str, Any] = field(default_factory=dict)

    def is_usable(self) -> bool:
        """Minimum bar to enter the pipeline: a title and some way to apply."""
        has_apply_path = bool(self.apply_url or self.apply_email or self.source_url)
        return bool(self.title and self.title.strip()) and has_apply_path


@dataclass(frozen=True, slots=True)
class SourceConfig:
    """Immutable view of a `sources` row for the adapter.

    Built by the pipeline (`app/ingestion/pipeline.py`) from the DB row. Frozen so
    an adapter cannot accidentally mutate shared state mid-run.
    """

    key: str
    name: str
    adapter: str
    kind: SourceKind
    base_url: str | None
    config: dict[str, Any]
    priority: int
    request_timeout_seconds: int
    rate_limit_per_min: int | None
    api_key_ref: str | None

    def cfg(self, name: str, default: Any = None) -> Any:
        """Read a key from the row's free-form `config` JSON."""
        return self.config.get(name, default)

    def secret(self, ref: str | None = None) -> str | None:
        """Resolve a credential by env-var name.

        Defaults to this source's own `api_key_ref`. Adapters that need a second
        credential (Adzuna's app id, USAJOBS' user-agent) pass its name
        explicitly. The value comes from `Settings`, never from the database.
        """
        return get_settings().resolve_api_key(ref or self.api_key_ref)


class SourceAdapter(abc.ABC):
    """Base class for every source adapter.

    Subclasses set `key` (matching `sources.adapter`) and `kind`, and implement
    `fetch`. They may override `default_base_url`. Keep `__init__` free of side
    effects — adapters are cheap to construct and are looked up by the registry.
    """

    #: Registry key; must equal the `sources.adapter` value that selects it.
    key: str = ""
    #: Structural kind — informs dedupe priority and logging.
    kind: SourceKind = SourceKind.AGGREGATOR
    #: Fallback endpoint if the `sources` row leaves `base_url` empty.
    default_base_url: str | None = None

    def base_url(self, config: SourceConfig) -> str:
        url = config.base_url or self.default_base_url
        if not url:
            raise ValueError(f"{self.key}: no base_url configured")
        return url.rstrip("/")

    @abc.abstractmethod
    def fetch(self, config: SourceConfig) -> Iterable[RawJob]:
        """Yield every currently-listed job for this source.

        Implementations SHOULD stream (yield as pages arrive) rather than build a
        giant list, and SHOULD respect `config.cfg('max_pages')` where the API
        is paginated. Network/parse errors for a *single* record should be
        swallowed with a log line; a failure that means "this whole page/board is
        unusable" should raise so the run is marked partial/failed.
        """
        raise NotImplementedError

    # Convenience for adapters that page over sub-resources (Greenhouse boards,
    # Lever companies): iterate the configured list with a sane default.
    @staticmethod
    def _iter_config_list(config: SourceConfig, *keys: str) -> Iterator[str]:
        for key in keys:
            values = config.cfg(key) or []
            yield from (str(v) for v in values)
