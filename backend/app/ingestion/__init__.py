"""Ingestion pipeline: external sources → normalized, deduped, stored jobs.

base.py       SourceAdapter ABC + RawJob dataclass (the adapter contract)
registry.py   adapter-key → adapter-class lookup
http.py       rate-limited, retrying, caching httpx wrapper for source calls
adapters/     one module per source shape (remotive, greenhouse, lever, …)
normalize.py  RawJob → NormalizedJob (all the messy parsing lives here)
dedupe.py     cross-source duplicate detection + canonical-row selection
pipeline.py   orchestrates fetch → normalize → dedupe → categorize → upsert
run.py        CLI: `python -m app.ingestion.run --source remotive`
"""
