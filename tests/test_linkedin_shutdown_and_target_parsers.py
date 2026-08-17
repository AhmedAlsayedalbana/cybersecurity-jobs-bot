"""Regression coverage for bounded LinkedIn shutdown and target board parsers."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest


def test_linkedin_timeout_joins_its_task_and_reports_shutdown(monkeypatch):
    import sources.linkedin_unified as linkedin

    completed = False

    async def slow_impl():
        nonlocal completed
        try:
            await asyncio.sleep(10)
        finally:
            completed = True

    monkeypatch.setattr(linkedin.config, "LINKEDIN_TOTAL_BUDGET_SECONDS", 0.01)
    monkeypatch.setattr(linkedin, "_fetch_linkedin_unified_impl", slow_impl)
    linkedin._LINKEDIN_PARTIAL_RESULTS = ["partial"]
    linkedin._LINKEDIN_TELEMETRY = {}
    linkedin._LINKEDIN_MANAGED_TASKS.clear()

    assert asyncio.run(linkedin.fetch_linkedin_unified_async()) == ["partial"]
    telemetry = linkedin.get_linkedin_telemetry()
    assert completed
    assert telemetry["pending_tasks_before"] == 1
    assert telemetry["cancelled_tasks"] == 1
    assert telemetry["pending_tasks_after"] == 0
    assert not linkedin._LINKEDIN_MANAGED_TASKS


@pytest.mark.parametrize("spec_key", ("wuzzuf", "tanqeeb", "upwork", "freelancer", "akhtaboot"))
def test_target_marketplace_parsers_keep_provider_fields(spec_key):
    from sources.marketplace_sources import SPECS_BY_KEY, _parse

    spec = SPECS_BY_KEY[spec_key]
    content = (
        '{"results":[{"jobId":"provider-42",'
        '"jobTitle":"Cybersecurity Analyst",'
        '"detail_url":"/jobs/cybersecurity-analyst-123",'
        '"companyName":"Acme Security",'
        '"locationName":"Cairo, Egypt",'
        f'"publishedAt":"{datetime.now().isoformat(timespec="seconds")}",'
        '"shortDescription":"SIEM and incident response security role"}]}'
    )

    jobs = _parse(content, spec, spec.urls[0], "direct")

    assert len(jobs) == 1
    assert jobs[0].company == "Acme Security"
    assert jobs[0].location == "Cairo, Egypt"
    assert jobs[0].posted_date is not None
    assert "job_id:provider-42" in jobs[0].tags


def test_wazzif_structured_parser_keeps_provider_fields(monkeypatch):
    import sources.egypt_boards as boards

    posted = datetime.now().isoformat(timespec="seconds")
    html = f'''<script type="application/ld+json">{{
        "@type":"JobPosting", "id":"wz-42", "title":"SOC Analyst",
        "url":"/jobs/soc-analyst-42", "datePosted":"{posted}",
        "description":"SIEM incident response", "hiringOrganization":{{"name":"Acme Egypt"}},
        "jobLocation":{{"name":"Cairo, Egypt"}}
    }}</script>'''

    class Response:
        status_code = 200
        text = html

    monkeypatch.setattr(boards.requests, "get", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(boards.time, "sleep", lambda *_args, **_kwargs: None)

    result = boards.fetch_wazzif()

    assert result.status == "success"
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert (job.company, job.location) == ("Acme Egypt", "Cairo, Egypt")
    assert "job_id:wz-42" in job.tags


def test_target_block_page_is_not_reported_as_parse_changed(monkeypatch):
    import sources.marketplace_sources as marketplace

    class TextResult:
        text = "Just a moment... Performing security verification"

    monkeypatch.setattr(marketplace, "get_text_result", lambda *_args, **_kwargs: TextResult())
    monkeypatch.setattr(marketplace, "_fetch_via_jina", lambda _url: TextResult.text)

    result = marketplace.fetch_marketplace("wuzzuf")

    assert result.status == "blocked"
    assert result.error_code == "wuzzuf_blocked"
