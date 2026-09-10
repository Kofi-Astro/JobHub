"""Adapter contract tests.

Each adapter is exercised against a recorded fixture payload (no network, no DB)
and must yield `RawJob`s that satisfy the shared contract:
    * a non-empty title,
    * an external_id,
    * some way to apply (`apply_url` or `source_url` or `apply_email`),
    * `raw` preserved for reprocessing.
Adapter-specific mappings (remote flag, salary passthrough, HTML unescaping) get
a targeted assertion too.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.ingestion.registry import get_adapter, known_adapters
from tests.conftest_ingestion import load_fixture, make_config


def _assert_contract(raw_jobs):
    assert raw_jobs, "adapter yielded nothing"
    for rj in raw_jobs:
        assert rj.title and rj.title.strip()
        assert rj.external_id
        assert rj.apply_url or rj.source_url or rj.apply_email
        assert isinstance(rj.raw, dict) and rj.raw
        assert rj.is_usable()


def test_registry_has_every_seeded_adapter():
    assert set(known_adapters()) == {
        "remotive",
        "remoteok",
        "arbeitnow",
        "greenhouse",
        "lever",
        "ashby",
        "adzuna",
        "jooble",
        "usajobs",
    }


@respx.mock
def test_remotive():
    respx.get("https://remotive.com/api/remote-jobs").respond(json=load_fixture("remotive.json"))
    jobs = list(get_adapter("remotive").fetch(make_config()))
    _assert_contract(jobs)
    assert len(jobs) == 2
    assert all(j.is_remote for j in jobs)
    assert jobs[0].salary_raw == "$120,000 - $160,000"
    assert jobs[0].job_type_hint == "full_time"
    # <script> content is not the adapter's problem, but the raw HTML is passed
    # through untouched for the normalizer to sanitize.
    assert "<script>" in jobs[0].description_html


@respx.mock
def test_remoteok_skips_metadata_row():
    respx.get("https://remoteok.com/api").respond(json=load_fixture("remoteok.json"))
    jobs = list(get_adapter("remoteok").fetch(make_config()))
    _assert_contract(jobs)
    assert len(jobs) == 2  # the leading {"legal": ...} object is dropped
    assert jobs[0].salary_min == 120000 and jobs[0].salary_max == 160000
    assert jobs[1].salary_min is None  # 0/0 treated as "unknown"


@respx.mock
def test_arbeitnow_pagination_stops_on_null_next():
    respx.get("https://www.arbeitnow.com/api/job-board-api").respond(
        json=load_fixture("arbeitnow.json")
    )
    jobs = list(get_adapter("arbeitnow").fetch(make_config(config={"max_pages": 5})))
    _assert_contract(jobs)
    assert len(jobs) == 2
    assert jobs[1].is_remote is True and jobs[0].is_remote is False


@respx.mock
def test_greenhouse_multi_board_and_unescape():
    fx = load_fixture("greenhouse.json")
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true").respond(json=fx)
    jobs = list(get_adapter("greenhouse").fetch(make_config(config={"board_tokens": ["acme"]})))
    _assert_contract(jobs)
    assert jobs[0].company_name == "Acme"
    # Greenhouse entity-encodes `content`; the adapter unescapes it to real HTML.
    assert jobs[0].description_html.startswith("<p>")
    assert jobs[0].category_hint == "Engineering"


@respx.mock
def test_greenhouse_one_dead_board_does_not_sink_the_source():
    ok = load_fixture("greenhouse.json")
    respx.get("https://boards-api.greenhouse.io/v1/boards/good/jobs?content=true").respond(json=ok)
    respx.get("https://boards-api.greenhouse.io/v1/boards/bad/jobs?content=true").respond(404)
    jobs = list(
        get_adapter("greenhouse").fetch(make_config(config={"board_tokens": ["good", "bad"]}))
    )
    assert len(jobs) == 2  # from "good" only


@respx.mock
def test_greenhouse_all_boards_dead_raises():
    respx.get(url__regex=r"https://boards-api\.greenhouse\.io/.*").respond(500)
    with pytest.raises(RuntimeError):
        list(get_adapter("greenhouse").fetch(make_config(config={"board_tokens": ["a", "b"]})))


@respx.mock
def test_lever_workplace_and_commitment_mapping():
    respx.get("https://api.lever.co/v0/postings/acme?mode=json").respond(
        json=load_fixture("lever.json")
    )
    jobs = list(get_adapter("lever").fetch(make_config(config={"companies": ["acme"]})))
    _assert_contract(jobs)
    assert jobs[0].workplace_hint == "hybrid"
    assert jobs[1].workplace_hint == "remote" and jobs[1].is_remote is True
    assert jobs[0].job_type_hint == "Full-time"
    assert jobs[0].description_text == "Lead the roadmap for our core product."


@respx.mock
def test_ashby_employment_type_and_listed_filter():
    respx.get(
        "https://api.ashbyhq.com/posting-api/job-board/Acme?includeCompensation=true"
    ).respond(json=load_fixture("ashby.json"))
    jobs = list(get_adapter("ashby").fetch(make_config(config={"orgs": ["Acme"]})))
    _assert_contract(jobs)
    assert jobs[0].job_type_hint == "full_time"
    assert jobs[1].job_type_hint == "internship"
    assert jobs[0].salary_raw == "$150K – $190K"


def test_keyed_adapters_refuse_without_credentials(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()  # ensure blank creds
    for key in ("adzuna", "jooble", "usajobs"):
        with pytest.raises(ValueError, match=r"not set|ADZUNA|JOOBLE|USAJOBS"):
            list(get_adapter(key).fetch(make_config(api_key_ref="X")))


@respx.mock
def test_transient_error_is_retried_then_succeeds():
    route = respx.get("https://remotive.com/api/remote-jobs")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(200, json=load_fixture("remotive.json")),
    ]
    jobs = list(get_adapter("remotive").fetch(make_config()))
    assert len(jobs) == 2
    assert route.call_count == 2
