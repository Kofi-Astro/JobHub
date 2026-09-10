"""API tests for search / filter / facets / detail / taxonomy / meta.

Uses a small hand-built set of jobs so assertions are exact.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Job, Source
from app.models.enums import (
    ExperienceLevel,
    JobOrigin,
    JobStatus,
    JobType,
    WorkplaceType,
)


@pytest.fixture
def jobs(seeded):
    db = seeded
    src = db.scalar(select(Source).where(Source.key == "remotive"))

    from app.models import Subfield

    webdev = db.scalar(select(Subfield).where(Subfield.slug == "web-development"))
    nursing = db.scalar(select(Subfield).where(Subfield.slug == "nursing"))

    def mk(**kw):
        base = {
            "origin": JobOrigin.AGGREGATED,
            "source_id": src.id,
            "status": JobStatus.ACTIVE,
            "is_canonical": True,
            "is_remote": False,
            "workplace_type": WorkplaceType.ONSITE,
            "job_type": JobType.FULL_TIME,
            "experience_level": ExperienceLevel.MID,
            "description_text": "",
            "company_name_raw": "Acme",
            "posted_at": datetime.now(UTC),
            "salary_is_disclosed": False,
        }
        base.update(kw)
        j = Job(**base)
        db.add(j)
        return j

    mk(
        external_id="1",
        title="Senior React Developer",
        description_text="react typescript frontend",
        country_code="DE",
        country_name="Germany",
        city="Berlin",
        field_id=webdev.field_id,
        subfield_id=webdev.id,
        salary_is_disclosed=True,
        salary_min=70000,
        salary_max=90000,
        salary_currency="EUR",
        salary_period="year",
    )
    mk(
        external_id="2",
        title="Registered Nurse",
        description_text="icu bedside care",
        country_code="US",
        country_name="United States",
        city="Austin",
        field_id=nursing.field_id,
        subfield_id=nursing.id,
        job_type=JobType.PART_TIME,
    )
    mk(
        external_id="3",
        title="Remote Backend Engineer",
        description_text="python fastapi",
        is_remote=True,
        workplace_type=WorkplaceType.REMOTE,
        remote_scope="Worldwide",
        field_id=webdev.field_id,
        subfield_id=webdev.id,
        posted_at=datetime.now(UTC) - timedelta(days=40),
    )
    db.flush()
    return db


def test_list_all_active(client, jobs):
    body = client.get("/api/jobs").json()
    assert body["total"] == 3
    assert {i["title"] for i in body["items"]} == {
        "Senior React Developer",
        "Registered Nurse",
        "Remote Backend Engineer",
    }


def test_full_text_search(client, jobs):
    assert client.get("/api/jobs?q=react").json()["total"] == 1
    assert client.get("/api/jobs?q=nurse").json()["total"] == 1
    assert client.get("/api/jobs?q=python").json()["total"] == 1


def test_filters_combine(client, jobs):
    # remote + web-development
    body = client.get("/api/jobs?remote=true&subfield=web-development").json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Remote Backend Engineer"


def test_country_filter(client, jobs):
    assert client.get("/api/jobs?country=DE").json()["total"] == 1
    assert client.get("/api/jobs?country=US&country=DE").json()["total"] == 2


def test_salary_filter_keeps_undisclosed_by_default(client, jobs):
    # Ask for >= 100k. The only disclosed job tops out at 90k EUR → excluded,
    # but the two undisclosed jobs still show (never hidden).
    body = client.get("/api/jobs?salary_min=100000").json()
    assert body["total"] == 2
    # Opt out of undisclosed → nothing matches.
    body2 = client.get("/api/jobs?salary_min=100000&include_undisclosed_salary=false").json()
    assert body2["total"] == 0


def test_date_posted_filter(client, jobs):
    assert client.get("/api/jobs?posted_within_days=7").json()["total"] == 2


def test_facets_reflect_filtered_set_but_not_their_own_dimension(client, jobs):
    facets = client.get("/api/jobs/facets?country=US").json()
    # total respects the country filter...
    assert facets["total"] == 1
    # ...but the countries facet still shows every country (its own filter is
    # ignored for its own counts).
    codes = {f["value"] for f in facets["countries"]}
    assert {"US", "DE"} <= codes


def test_job_detail_and_beacons(client, jobs):
    jid = client.get("/api/jobs").json()["items"][0]["id"]
    detail = client.get(f"/api/jobs/{jid}").json()
    assert "description_html" in detail and "also_listed_on" in detail

    assert client.post(f"/api/jobs/{jid}/view").status_code == 204
    apply = client.post(f"/api/jobs/{jid}/apply-click").json()
    assert "url" in apply

    job = jobs.get(Job, jid)
    jobs.refresh(job)
    assert job.view_count == 1
    assert job.apply_click_count == 1


def test_taxonomy_endpoint(client, seeded):
    tree = client.get("/api/taxonomy").json()
    assert len(tree["fields"]) >= 12
    tech = next(f for f in tree["fields"] if f["slug"] == "computing-tech")
    assert any(s["slug"] == "web-development" for s in tech["subfields"])


def test_meta_countries_and_sources(client, jobs):
    countries = client.get("/api/meta/countries").json()
    assert {c["code"] for c in countries} == {"DE", "US"}
    sources = client.get("/api/meta/sources").json()
    assert any(s["key"] == "remotive" and s["job_count"] == 3 for s in sources)


def test_unknown_job_is_404(client, seeded):
    assert client.get("/api/jobs/00000000-0000-0000-0000-000000000000").status_code == 404
