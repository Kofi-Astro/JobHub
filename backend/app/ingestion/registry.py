"""Adapter registry: `sources.adapter` string → adapter instance.

Adapters self-register with the `@register` decorator when their module is
imported. `app.ingestion.adapters` imports every adapter module, so importing
`app.ingestion.registry` (which imports that package) is enough to populate it.

This is what makes "add a source that fits an existing shape" a pure config
change: a new Greenhouse board is a `sources` row with `adapter='greenhouse'`
and a `config.board_tokens` entry — no code. A genuinely new API shape is one
new module with `@register` and one class.
"""

from __future__ import annotations

from app.ingestion.base import SourceAdapter

_REGISTRY: dict[str, type[SourceAdapter]] = {}


def register(cls: type[SourceAdapter]) -> type[SourceAdapter]:
    """Class decorator — record an adapter under its `key`."""
    if not cls.key:
        raise ValueError(f"{cls.__name__} must set a non-empty `key`")
    if cls.key in _REGISTRY and _REGISTRY[cls.key] is not cls:
        raise ValueError(f"duplicate adapter key {cls.key!r}")
    _REGISTRY[cls.key] = cls
    return cls


def get_adapter(adapter_key: str) -> SourceAdapter:
    """Instantiate the adapter for a `sources.adapter` value."""
    # Import for side-effect: every adapter module runs its @register.
    import app.ingestion.adapters  # noqa: F401

    try:
        return _REGISTRY[adapter_key]()
    except KeyError:
        raise LookupError(
            f"no adapter registered for {adapter_key!r}; known: {sorted(_REGISTRY)}"
        ) from None


def known_adapters() -> list[str]:
    import app.ingestion.adapters  # noqa: F401

    return sorted(_REGISTRY)
