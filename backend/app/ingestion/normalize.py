"""Normalization: `RawJob` → `NormalizedJob`.

This is the one place messy, source-specific strings become the clean, typed
values the rest of the system relies on. Adapters stay dumb; this module carries
the parsing burden and is exhaustively unit-tested (table-driven) because it is
where subtle bugs (wrong currency, mis-parsed "K", a remote job marked on-site)
would silently degrade the product.

Pipeline position:  fetch → **normalize** → dedupe → categorize → store
"""

from __future__ import annotations

import hashlib
import html as html_lib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import bleach
import pycountry
from dateutil import parser as dateparser

from app.ingestion.base import RawJob
from app.models.enums import (
    ExperienceLevel,
    JobType,
    SalaryPeriod,
    WorkplaceType,
)
from app.util.text import normalize_company_name

# ---------------------------------------------------------------------------
# NormalizedJob — the cleaned, typed record handed to dedupe/categorize/store
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class NormalizedJob:
    # identity / provenance (carried through from RawJob + the source row)
    external_id: str | None
    source_url: str | None
    apply_url: str | None
    apply_email: str | None
    raw: dict

    # content
    title: str
    company_name_raw: str
    company_match_key: str
    description_html: str
    description_text: str

    # location
    location_raw: str | None
    city: str | None
    region: str | None
    country_code: str | None
    country_name: str | None
    is_remote: bool
    workplace_type: WorkplaceType
    remote_scope: str | None

    # compensation
    salary_min: Decimal | None
    salary_max: Decimal | None
    salary_currency: str | None
    salary_period: SalaryPeriod | None
    salary_is_disclosed: bool

    # classification (job_type/experience only — field/sub-field come later)
    job_type: JobType
    experience_level: ExperienceLevel
    category_hint: str | None
    tags: list[str] = field(default_factory=list)

    # dates
    posted_at: datetime | None = None

    # dedupe
    dedupe_hash: str = ""


# ---------------------------------------------------------------------------
# HTML sanitising
# ---------------------------------------------------------------------------

_ALLOWED_TAGS = [
    "p",
    "br",
    "hr",
    "ul",
    "ol",
    "li",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "a",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "blockquote",
    "code",
    "pre",
    "table",
    "thead",
    "tbody",
    "tr",
    "td",
    "th",
    "span",
    "div",
]
_ALLOWED_ATTRS = {"a": ["href", "title", "rel"]}
_WS = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\n\s*\n\s*\n+")


_DANGEROUS_BLOCK = re.compile(
    r"<(script|style|template|noscript)[\s\S]*?</\1\s*>|<!--[\s\S]*?-->", re.I
)


def sanitize_html(raw: str | None) -> str:
    """Strip scripts/styles/unknown tags; keep a safe subset for rendering.

    bleach's strip=True removes a disallowed tag but KEEPS its text content —
    wrong for <script>/<style>, whose content must go too. `_DANGEROUS_BLOCK`
    drops those whole blocks (and HTML comments) before bleach sees them.
    """
    if not raw:
        return ""
    raw = _DANGEROUS_BLOCK.sub("", raw)
    cleaned = bleach.clean(raw, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS, strip=True)
    # Force every link to open safely and not pass referrer/opener.
    return cleaned.replace("<a ", '<a rel="noopener nofollow" target="_blank" ')


def html_to_text(raw: str | None) -> str:
    """Plain text for search + the keyword classifier."""
    if not raw:
        return ""
    text = bleach.clean(_DANGEROUS_BLOCK.sub("", raw), tags=[], strip=True)
    text = html_lib.unescape(text)
    text = _WS.sub(" ", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

_REMOTE_RE = re.compile(r"\b(remote|anywhere|work from home|wfh|distributed)\b", re.I)
_HYBRID_RE = re.compile(r"\bhybrid\b", re.I)
_ONSITE_RE = re.compile(r"\b(on[\s-]?site|in[\s-]?office|in[\s-]?person)\b", re.I)

# Common informal names / abbreviations pycountry does not resolve directly.
_COUNTRY_ALIASES = {
    "usa": "US",
    "u.s.a.": "US",
    "u.s.": "US",
    "us": "US",
    "united states": "US",
    "america": "US",
    "uk": "GB",
    "u.k.": "GB",
    "britain": "GB",
    "great britain": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "northern ireland": "GB",
    "uae": "AE",
    "south korea": "KR",
    "korea": "KR",
    "russia": "RU",
    "vietnam": "VN",
    "laos": "LA",
    "czech republic": "CZ",
    "czechia": "CZ",
    "ivory coast": "CI",
    "türkiye": "TR",
    "turkey": "TR",
    "the netherlands": "NL",
    "holland": "NL",
}
# US state codes → so "San Francisco, CA" resolves to the US.
_US_STATES = {
    "al",
    "ak",
    "az",
    "ar",
    "ca",
    "co",
    "ct",
    "de",
    "fl",
    "ga",
    "hi",
    "id",
    "il",
    "in",
    "ia",
    "ks",
    "ky",
    "la",
    "me",
    "md",
    "ma",
    "mi",
    "mn",
    "ms",
    "mo",
    "mt",
    "ne",
    "nv",
    "nh",
    "nj",
    "nm",
    "ny",
    "nc",
    "nd",
    "oh",
    "ok",
    "or",
    "pa",
    "ri",
    "sc",
    "sd",
    "tn",
    "tx",
    "ut",
    "vt",
    "va",
    "wa",
    "wv",
    "wi",
    "wy",
    "dc",
}


def _resolve_country(token: str) -> tuple[str, str] | None:
    """(alpha_2, name) for a country name/code token, or None."""
    t = token.strip().lower().strip(".")
    if not t:
        return None
    if t in _COUNTRY_ALIASES:
        code = _COUNTRY_ALIASES[t]
        return code, pycountry.countries.get(alpha_2=code).name
    if t in _US_STATES:
        return "US", "United States"
    try:
        match = pycountry.countries.lookup(token.strip())
        return match.alpha_2, match.name
    except LookupError:
        return None


def parse_location(
    raw: RawJob,
) -> tuple[str | None, str | None, str | None, str | None, bool, WorkplaceType, str | None]:
    """Return (city, region, country_code, country_name, is_remote,
    workplace_type, remote_scope).

    Honours structured hints the adapter already set; only parses `location_raw`
    for anything still missing.
    """
    loc = (raw.location_raw or "").strip()
    hint = (raw.workplace_hint or "").strip().lower()

    is_remote = bool(raw.is_remote) or bool(_REMOTE_RE.search(loc)) or hint == "remote"
    if _HYBRID_RE.search(loc) or hint == "hybrid":
        workplace = WorkplaceType.HYBRID
    elif is_remote:
        workplace = WorkplaceType.REMOTE
    elif _ONSITE_RE.search(loc) or hint in {"on-site", "onsite", "office"} or loc:
        workplace = WorkplaceType.ONSITE
    else:
        workplace = WorkplaceType.UNKNOWN

    remote_scope = raw.remote_scope
    if is_remote and not remote_scope and loc:
        # "Remote (US)", "Remote - EMEA", "Worldwide" → keep the qualifier text.
        scope = _REMOTE_RE.sub("", loc).strip(" ()-–—,")
        remote_scope = scope or (loc if loc.lower() != "remote" else None)

    city = raw.city
    region = raw.region
    country_code = (raw.country_code or "").upper() or None
    country_name = raw.country_name

    if not country_code and loc:
        # Strip a leading "Remote" qualifier before parsing the geography.
        geo = _REMOTE_RE.sub("", loc).strip(" ()-–—,")
        parts = [p.strip() for p in re.split(r"[,/|]", geo) if p.strip()]
        if parts:
            resolved = _resolve_country(parts[-1])
            if resolved:
                country_code, country_name = resolved
                rest = parts[:-1]
                if rest and not city:
                    city = rest[0]
                if len(rest) > 1 and not region:
                    region = rest[1]
            elif not city and not is_remote:
                # For an on-site job with an unrecognised location, treat the
                # first token as the city. For a remote job the leftover is a
                # region/scope descriptor ("EMEA", "Worldwide"), not a city.
                city = parts[0]

    if country_code and not country_name:
        rec = pycountry.countries.get(alpha_2=country_code)
        country_name = rec.name if rec else None

    return city, region, country_code, country_name, is_remote, workplace, remote_scope


# ---------------------------------------------------------------------------
# Salary
# ---------------------------------------------------------------------------

_CURRENCY_SYMBOL = {"$": "USD", "£": "GBP", "€": "EUR", "₹": "INR", "R$": "BRL", "¥": "JPY"}
# Ordered most-specific first. Each matches "per X", "/X", "/Xly", or a bare
# period word, so "90000/year", "£45 per hour" and "50k annually" all resolve.
_PERIOD_RE = [
    (re.compile(r"(per\s*hour|/\s*h(r|our)?|hourly|an hour|\bp/?h\b)", re.I), SalaryPeriod.HOUR),
    (re.compile(r"(per\s*day|/\s*day|daily|per diem)", re.I), SalaryPeriod.DAY),
    (re.compile(r"(per\s*week|/\s*w(k|eek)?|weekly)", re.I), SalaryPeriod.WEEK),
    (re.compile(r"(per\s*month|/\s*mo(nth)?|monthly|a month|\bpcm\b)", re.I), SalaryPeriod.MONTH),
    (
        re.compile(
            r"(per\s*(annum|year)|/\s*y(r|ear)?|annual(ly)?|p\.?a\.?|yearly|a year|\byear\b)", re.I
        ),
        SalaryPeriod.YEAR,
    ),
]
_NUM_RE = re.compile(r"(\d[\d,\.]*)\s*([kKmM])?")
_CODE_RE = re.compile(r"\b([A-Z]{3})\b")


def _num_to_decimal(digits: str, suffix: str | None) -> Decimal | None:
    try:
        value = Decimal(digits.replace(",", ""))
    except InvalidOperation:
        return None
    if suffix in {"k", "K"}:
        value *= 1000
    elif suffix in {"m", "M"}:
        value *= 1_000_000
    return value


def parse_salary(
    raw: RawJob,
) -> tuple[Decimal | None, Decimal | None, str | None, SalaryPeriod | None, bool]:
    """Return (min, max, currency, period, is_disclosed).

    Prefers structured numeric fields the adapter set; otherwise parses the free
    text `salary_raw`. A "predicted"/estimated figure the adapter chose to drop
    simply never arrives here, so it is correctly treated as not disclosed.
    """
    # 1. Structured path.
    if raw.salary_min is not None or raw.salary_max is not None:
        smin = _coerce(raw.salary_min)
        smax = _coerce(raw.salary_max) or smin
        period = _period_from_str(raw.salary_period) or SalaryPeriod.YEAR
        return smin, smax, (raw.salary_currency or "USD").upper(), period, True

    text = (raw.salary_raw or "").strip()
    if not text or text.lower() in {"n/a", "not disclosed", "competitive", "doe", "-"}:
        return None, None, None, None, False

    # 2. Free-text path.
    currency = None
    for sym, code in _CURRENCY_SYMBOL.items():
        if sym in text:
            currency = code
            break
    if not currency:
        m = _CODE_RE.search(text)
        if m and m.group(1) not in {"NEW", "AND", "THE", "FOR"}:
            currency = m.group(1)

    period = None
    for rx, p in _PERIOD_RE:
        if rx.search(text):
            period = p
            break

    numbers = [_num_to_decimal(d, s) for d, s in _NUM_RE.findall(text)]
    numbers = [n for n in numbers if n is not None]

    # Minimum plausible figure depends on the period: an hourly rate can be $15,
    # a yearly one should not be. This filters out stray digits ("2 years'
    # experience", "top 1%") without discarding real short-period pay.
    floor = {
        SalaryPeriod.HOUR: 3,
        SalaryPeriod.DAY: 20,
        SalaryPeriod.WEEK: 100,
        SalaryPeriod.MONTH: 300,
        SalaryPeriod.YEAR: 1000,
    }.get(period, 3 if period else 1000)
    numbers = [n for n in numbers if n >= floor]
    if not numbers:
        return None, None, currency, period, False

    smin = min(numbers)
    smax = max(numbers)
    # No explicit period: a large figure is yearly, a small one hourly.
    if period is None:
        period = SalaryPeriod.YEAR if smax >= 1000 else SalaryPeriod.HOUR
    return smin, smax, currency, period, True


def _coerce(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _period_from_str(value: str | None) -> SalaryPeriod | None:
    if not value:
        return None
    v = value.strip().lower()
    mapping = {
        "year": SalaryPeriod.YEAR,
        "yearly": SalaryPeriod.YEAR,
        "annual": SalaryPeriod.YEAR,
        "month": SalaryPeriod.MONTH,
        "monthly": SalaryPeriod.MONTH,
        "week": SalaryPeriod.WEEK,
        "weekly": SalaryPeriod.WEEK,
        "day": SalaryPeriod.DAY,
        "daily": SalaryPeriod.DAY,
        "hour": SalaryPeriod.HOUR,
        "hourly": SalaryPeriod.HOUR,
    }
    return mapping.get(v)


# ---------------------------------------------------------------------------
# Job type / experience level
# ---------------------------------------------------------------------------

_JOB_TYPE_MAP = {
    "full_time": JobType.FULL_TIME,
    "full-time": JobType.FULL_TIME,
    "fulltime": JobType.FULL_TIME,
    "permanent": JobType.FULL_TIME,
    "full time": JobType.FULL_TIME,
    "part_time": JobType.PART_TIME,
    "part-time": JobType.PART_TIME,
    "part time": JobType.PART_TIME,
    "contract": JobType.CONTRACT,
    "contractor": JobType.CONTRACT,
    "freelance": JobType.CONTRACT,
    "fixed-term": JobType.CONTRACT,
    "b2b": JobType.CONTRACT,
    "internship": JobType.INTERNSHIP,
    "intern": JobType.INTERNSHIP,
    "trainee": JobType.INTERNSHIP,
    "temporary": JobType.TEMPORARY,
    "temp": JobType.TEMPORARY,
    "seasonal": JobType.TEMPORARY,
}
_INTERN_TITLE_RE = re.compile(r"\b(intern|internship|co[\s-]?op|working student)\b", re.I)
_CONTRACT_TITLE_RE = re.compile(r"\b(contract|contractor|freelance)\b", re.I)

_SENIOR_RE = re.compile(r"\b(senior|sr\.?|staff|principal|lead|head of|director|vp|chief)\b", re.I)
_LEAD_RE = re.compile(r"\b(lead|principal|staff|head of|manager)\b", re.I)
_ENTRY_RE = re.compile(
    r"\b(junior|jr\.?|entry[\s-]?level|graduate|intern|trainee|apprentice)\b", re.I
)


def map_job_type(raw: RawJob) -> JobType:
    hint = (raw.job_type_hint or "").strip().lower()
    if hint in _JOB_TYPE_MAP:
        return _JOB_TYPE_MAP[hint]
    title = raw.title or ""
    if _INTERN_TITLE_RE.search(title):
        return JobType.INTERNSHIP
    if _CONTRACT_TITLE_RE.search(title):
        return JobType.CONTRACT
    if hint:
        return JobType.OTHER
    return JobType.UNKNOWN


def map_experience(raw: RawJob) -> ExperienceLevel:
    hint = (raw.experience_hint or "").strip().lower()
    explicit = {
        "entry": ExperienceLevel.ENTRY,
        "entry-level": ExperienceLevel.ENTRY,
        "junior": ExperienceLevel.ENTRY,
        "associate": ExperienceLevel.ENTRY,
        "mid": ExperienceLevel.MID,
        "mid-level": ExperienceLevel.MID,
        "intermediate": ExperienceLevel.MID,
        "senior": ExperienceLevel.SENIOR,
        "expert": ExperienceLevel.SENIOR,
        "lead": ExperienceLevel.LEAD,
        "principal": ExperienceLevel.LEAD,
        "staff": ExperienceLevel.LEAD,
        "director": ExperienceLevel.LEAD,
    }
    if hint in explicit:
        return explicit[hint]

    title = raw.title or ""
    if _ENTRY_RE.search(title):
        return ExperienceLevel.ENTRY
    if _LEAD_RE.search(title):
        return ExperienceLevel.LEAD
    if _SENIOR_RE.search(title):
        return ExperienceLevel.SENIOR
    return ExperienceLevel.UNKNOWN


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


def parse_posted_at(raw_value: str | None) -> datetime | None:
    """Parse an ISO string, or a unix epoch in seconds or milliseconds."""
    if not raw_value:
        return None
    value = str(raw_value).strip()
    if not value or value.lower() in {"none", "null"}:
        return None

    if value.lstrip("-").isdigit():
        num = int(value)
        if num > 10_000_000_000:  # milliseconds
            num //= 1000
        try:
            return datetime.fromtimestamp(num, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        dt = dateparser.parse(value)
    except (ValueError, OverflowError, TypeError):
        return None
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# Dedupe hash
# ---------------------------------------------------------------------------


def compute_dedupe_hash(company_match_key: str, title: str, country_code: str | None) -> str:
    """Stable sha1 of the identity of a role, for cross-source dedupe.

    Deliberately coarse: company + normalized title + country. Workplace type is
    intentionally NOT part of the key — an aggregator that blanket-labels every
    job "remote" and the company's own board that says "United States" describe
    the SAME role, and must still merge. Two genuinely-different roles at one
    company in one country almost always differ in title, so false merges are
    rare; and a coarse key errs toward under-merging (a harmless visible
    duplicate) rather than over-merging (hiding a real job).
    """
    title_key = re.sub(r"[^a-z0-9 ]", "", (title or "").lower())
    title_key = re.sub(r"\s+", " ", title_key).strip()
    basis = f"{company_match_key}|{title_key}|{country_code or ''}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def normalize(raw: RawJob) -> NormalizedJob:
    """Turn one `RawJob` into a fully-typed `NormalizedJob`.

    Assumes `raw.is_usable()` has already been checked by the pipeline.
    """
    title = (raw.title or "").strip()
    company_raw = (raw.company_name or "").strip() or "Unknown"
    company_key = normalize_company_name(company_raw)

    description_html = sanitize_html(raw.description_html)
    description_text = raw.description_text or html_to_text(
        raw.description_html or raw.description_text
    )

    city, region, cc, cname, is_remote, workplace, scope = parse_location(raw)
    smin, smax, currency, period, disclosed = parse_salary(raw)

    return NormalizedJob(
        external_id=raw.external_id,
        source_url=raw.source_url,
        apply_url=raw.apply_url or raw.source_url,
        apply_email=raw.apply_email,
        raw=raw.raw or {},
        title=title,
        company_name_raw=company_raw,
        company_match_key=company_key,
        description_html=description_html,
        description_text=description_text,
        location_raw=raw.location_raw,
        city=city,
        region=region,
        country_code=cc,
        country_name=cname,
        is_remote=is_remote,
        workplace_type=workplace,
        remote_scope=scope,
        salary_min=smin,
        salary_max=smax,
        salary_currency=currency,
        salary_period=period,
        salary_is_disclosed=disclosed,
        job_type=map_job_type(raw),
        experience_level=map_experience(raw),
        category_hint=raw.category_hint,
        tags=[t for t in (raw.tags or []) if t][:20],
        posted_at=parse_posted_at(raw.posted_at_raw),
        dedupe_hash=compute_dedupe_hash(company_key, title, cc),
    )
