"""Table-driven tests for the normalizer — the highest-risk parsing code."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.ingestion.base import RawJob
from app.ingestion.normalize import (
    normalize,
    parse_salary,
    sanitize_html,
)
from app.models.enums import ExperienceLevel, JobType, SalaryPeriod, WorkplaceType


@pytest.mark.parametrize(
    ("location_raw", "is_remote_hint", "workplace_hint", "expect_cc", "expect_city", "expect_wt"),
    [
        ("Berlin, Germany", None, None, "DE", "Berlin", WorkplaceType.ONSITE),
        ("San Francisco, CA", None, None, "US", "San Francisco", WorkplaceType.ONSITE),
        ("London, UK", None, None, "GB", "London", WorkplaceType.ONSITE),
        ("Remote", True, None, None, None, WorkplaceType.REMOTE),
        ("Remote (US)", None, None, "US", None, WorkplaceType.REMOTE),
        ("Remote - EMEA", True, None, None, None, WorkplaceType.REMOTE),
        ("Toronto, Ontario, Canada", None, "hybrid", "CA", "Toronto", WorkplaceType.HYBRID),
        ("", None, None, None, None, WorkplaceType.UNKNOWN),
        ("Worldwide", True, None, None, None, WorkplaceType.REMOTE),
    ],
)
def test_location_parsing(
    location_raw, is_remote_hint, workplace_hint, expect_cc, expect_city, expect_wt
):
    n = normalize(
        RawJob(
            title="Engineer",
            company_name="X",
            apply_url="http://x",
            location_raw=location_raw,
            is_remote=is_remote_hint,
            workplace_hint=workplace_hint,
        )
    )
    assert n.country_code == expect_cc
    assert n.city == expect_city
    assert n.workplace_type == expect_wt
    # Only fully-remote roles set is_remote; hybrid is its own thing.
    if expect_wt == WorkplaceType.REMOTE:
        assert n.is_remote is True


@pytest.mark.parametrize(
    ("text", "exp_min", "exp_max", "exp_cur", "exp_period", "disclosed"),
    [
        ("$120,000 - $160,000", 120000, 160000, "USD", SalaryPeriod.YEAR, True),
        ("€50k – €70k per year", 50000, 70000, "EUR", SalaryPeriod.YEAR, True),
        ("£45 per hour", 45, 45, "GBP", SalaryPeriod.HOUR, True),
        ("$150K – $190K", 150000, 190000, "USD", SalaryPeriod.YEAR, True),
        ("Competitive", None, None, None, None, False),
        ("", None, None, None, None, False),
        ("USD 90000/year", 90000, 90000, "USD", SalaryPeriod.YEAR, True),
    ],
)
def test_salary_freetext(text, exp_min, exp_max, exp_cur, exp_period, disclosed):
    smin, smax, cur, period, is_disclosed = parse_salary(RawJob(salary_raw=text))
    assert is_disclosed is disclosed
    if disclosed:
        assert smin == Decimal(exp_min)
        assert smax == Decimal(exp_max)
        assert cur == exp_cur
        assert period == exp_period


def test_salary_structured_fields_win_over_text():
    smin, smax, cur, period, disclosed = parse_salary(
        RawJob(salary_min=80000, salary_max=100000, salary_currency="cad", salary_period="year")
    )
    assert (smin, smax, cur, period, disclosed) == (
        Decimal(80000),
        Decimal(100000),
        "CAD",
        SalaryPeriod.YEAR,
        True,
    )


@pytest.mark.parametrize(
    ("title", "hint", "expected"),
    [
        ("Senior Software Engineer", None, JobType.UNKNOWN),
        ("Backend Engineer", "full_time", JobType.FULL_TIME),
        ("Marketing Intern", None, JobType.INTERNSHIP),
        ("Freelance Illustrator", None, JobType.CONTRACT),
        ("Anything", "permanent", JobType.FULL_TIME),
        ("Anything", "b2b", JobType.CONTRACT),
    ],
)
def test_job_type_mapping(title, hint, expected):
    n = normalize(RawJob(title=title, company_name="X", apply_url="http://x", job_type_hint=hint))
    assert n.job_type == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Senior Backend Engineer", ExperienceLevel.SENIOR),
        ("Junior Data Analyst", ExperienceLevel.ENTRY),
        ("Staff Engineer", ExperienceLevel.LEAD),
        ("Software Engineer", ExperienceLevel.UNKNOWN),
        ("Graduate Software Developer", ExperienceLevel.ENTRY),
    ],
)
def test_experience_from_title(title, expected):
    n = normalize(RawJob(title=title, company_name="X", apply_url="http://x"))
    assert n.experience_level == expected


def test_sanitize_html_drops_scripts_keeps_structure():
    out = sanitize_html("<p>Hello <b>world</b></p><script>alert(1)</script><img src=x onerror=y>")
    assert "<script>" not in out and "alert(1)" not in out
    assert "<p>Hello <b>world</b></p>" in out
    assert "<img" not in out


def test_dedupe_hash_is_stable_and_ignores_source():
    a = normalize(
        RawJob(
            title="Senior Python Engineer!",
            company_name="Acme Inc.",
            apply_url="http://a",
            location_raw="Remote",
            is_remote=True,
        )
    )
    b = normalize(
        RawJob(
            title="senior python engineer",
            company_name="Acme",
            source_url="http://b",
            location_raw="Remote",
            is_remote=True,
        )
    )
    assert a.dedupe_hash == b.dedupe_hash


def test_posted_at_accepts_epoch_seconds_ms_and_iso():
    for value in ("1704067200", "1704067200000", "2024-01-01T00:00:00Z"):
        n = normalize(
            RawJob(title="x", company_name="y", apply_url="http://x", posted_at_raw=value)
        )
        assert n.posted_at is not None and n.posted_at.year == 2024
