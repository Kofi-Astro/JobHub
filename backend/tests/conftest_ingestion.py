"""Ingestion-test helpers, imported by the ingestion test modules.

(Not named `conftest.py` so it stays an explicit import, not an auto-fixture.)
"""

from __future__ import annotations

import json
from pathlib import Path

from app.ingestion.base import SourceConfig
from app.models.enums import SourceKind

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict | list:
    return json.loads((FIXTURES / name).read_text())


def make_config(**overrides) -> SourceConfig:
    """A SourceConfig with sensible defaults; override per test."""
    defaults = {
        "key": "test",
        "name": "Test Source",
        "adapter": "test",
        "kind": SourceKind.AGGREGATOR,
        "base_url": None,
        "config": {},
        "priority": 10,
        "request_timeout_seconds": 5,
        "rate_limit_per_min": None,  # no throttling delay in tests
        "api_key_ref": None,
    }
    defaults.update(overrides)
    return SourceConfig(**defaults)
