"""Regression coverage for source and delivery observability upgrades."""

from __future__ import annotations

from types import SimpleNamespace


def test_budget_expansion_keeps_linkedin_ceiling_unchanged():
    import config

    # v61: LinkedIn Jobs budget doubled to 1800s, HR posts to 90s.
    # Total run budget = 1800 + 90 + 180 + 90 = 2160 (overhead adds to 2400 env default).
    assert config.OTHER_SOURCES_BUDGET_SECONDS == 180
    assert config.FILTERING_BUDGET_SECONDS == 90
    assert config.LINKEDIN_TOTAL_BUDGET_SECONDS == config.LINKEDIN_JOBS_BUDGET_SECONDS + config.LINKEDIN_HR_POSTS_BUDGET_SECONDS
    assert config.LINKEDIN_JOBS_BUDGET_SECONDS == 1800
    assert config.LINKEDIN_HR_POSTS_BUDGET_SECONDS == 90


def test_jsearch_without_a_key_reports_not_configured(monkeypatch):
    import config
    from sources.jsearch_enhanced import fetch_jsearch_enhanced
    from sources.marketplace_sources import SourceResult

    monkeypatch.setattr(config, "RAPIDAPI_KEY", "")
    result = fetch_jsearch_enhanced()

    assert isinstance(result, SourceResult)
    assert result.status == "not_configured"
    assert result.transport == "none"
    assert result.error_code == "missing_rapidapi_key"


def test_indeed_parser_accepts_current_anchor_shape_and_explicit_date(monkeypatch):
    from sources.priority_sources import fetch_indeed_public
    from sources.marketplace_sources import SourceResult
    import sources.priority_sources as priority_sources

    html = (
        '<a class="jcs-JobTitle" href="/viewjob?jk=abc123" '
        'aria-label="Cyber Security Analyst"><span title="Cyber Security Analyst">'
        'Cyber Security Analyst</span></a><span>Posted 2 hours ago</span>'
    )
    monkeypatch.setattr(
        priority_sources,
        "get_text_result",
        lambda *_args, **_kwargs: SimpleNamespace(text=html, error_code=""),
    )

    result = fetch_indeed_public()

    assert isinstance(result, SourceResult)
    assert result.status == "success"
    assert len(result.jobs) == 1
    assert result.jobs[0].title == "Cyber Security Analyst"
    assert result.jobs[0].posted_date is not None


def test_hr_telemetry_records_public_search_fallback(monkeypatch):
    from sources import linkedin_hr_posts_scraper as scraper

    post_url = "https://www.linkedin.com/feed/update/urn:li:activity:7341234567890123456/"
    bing_html = f'<html><a href="{post_url}">Hiring</a></html>'
    scraper._reset_hr_telemetry(budget_seconds=25, queries_planned=1)
    with monkeypatch.context() as ctx:
        ctx.setattr(scraper, "GOOGLE_CSE_API_KEY", "")
        ctx.setattr(scraper, "GOOGLE_CSE_CX", "")
        ctx.setattr(scraper, "SERPAPI_KEY", "")
        ctx.setattr(scraper, "get_text", lambda *_args, **_kwargs: bing_html)
        assert scraper._search_urls('site:linkedin.com/posts "#hiring" cybersecurity Egypt')

    telemetry = scraper.get_hr_post_telemetry()
    assert telemetry["search_backend_hits"] == {"bing_html": 1}

