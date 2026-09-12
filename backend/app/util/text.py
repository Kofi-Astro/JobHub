"""Text helpers used by seeding, ingestion normalization, and the API.

Kept free of heavy dependencies so it is cheap to import anywhere.
"""

from __future__ import annotations

import re
import unicodedata

# Legal-form suffixes stripped when building a company's `match_key`, so
# "Acme, Inc.", "Acme LLC" and "Acme" collapse to the same directory row.
_COMPANY_SUFFIXES = {
    "inc",
    "inc.",
    "llc",
    "l.l.c.",
    "ltd",
    "ltd.",
    "limited",
    "corp",
    "corp.",
    "corporation",
    "co",
    "co.",
    "company",
    "gmbh",
    "ag",
    "sa",
    "s.a.",
    "srl",
    "bv",
    "b.v.",
    "plc",
    "pty",
    "pvt",
    "kk",
    "oy",
    "ab",
    "as",
    "nv",
    "spa",
}

_slug_strip = re.compile(r"[^a-z0-9]+")
_ws = re.compile(r"\s+")


def slugify(value: str, *, max_length: int = 80) -> str:
    """URL-safe slug: ASCII-fold, lowercase, non-alphanumerics → single hyphen.

    Used for `fields.slug`, `subfields.slug`, `companies.slug`. Deterministic so
    re-running seeds produces the same slug for the same name.
    """
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = _slug_strip.sub("-", value.lower()).strip("-")
    return value[:max_length].strip("-") or "item"


def normalize_company_name(name: str) -> str:
    """Build the `companies.match_key` for a raw company name.

    Lowercase, strip punctuation and a trailing legal-form suffix, collapse
    whitespace. NOT a slug (keeps spaces) — it is a match key, compared for
    equality during ingestion's create-or-get of the company row.
    """
    cleaned = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^\w\s&-]", " ", cleaned.lower())
    cleaned = _ws.sub(" ", cleaned).strip()

    tokens = cleaned.split(" ")
    while tokens and tokens[-1].strip(".") in _COMPANY_SUFFIXES:
        tokens.pop()
    return " ".join(tokens).strip() or cleaned


def truncate(text: str, limit: int, *, suffix: str = "…") -> str:
    """Trim to `limit` characters on a word boundary where possible."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - len(suffix)]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip() + suffix
