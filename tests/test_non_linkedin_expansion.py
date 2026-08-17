"""Tests for non-LinkedIn source expansion."""


def test_recruitment_agencies_import():
    from sources.recruitment_agencies import fetch_recruitment_agencies, _AGENCY_SPECS
    assert len(_AGENCY_SPECS) >= 3
    assert callable(fetch_recruitment_agencies)


def test_arab_careers_import():
    from sources.arab_careers import fetch_arab_careers, _ARAB_COMPANY_SPECS
    assert len(_ARAB_COMPANY_SPECS) >= 10
    assert callable(fetch_arab_careers)


def test_source_health_import():
    from sources.source_health import (
        record_source_run, get_source_health, classify_zero_reason,
        get_zero_sources_report, compute_source_yield_score,
    )
    record_source_run("test_source", "success", jobs_count=5)
    health = get_source_health()
    assert "test_source" in health
    assert health["test_source"]["runs_healthy"] == 1
    assert health["test_source"]["total_jobs_found"] == 5


def test_classify_zero_reason():
    from sources.source_health import classify_zero_reason
    assert classify_zero_reason("x", "blocked") == "BLOCKED"
    assert classify_zero_reason("x", "empty") == "EMPTY_REAL"
    assert classify_zero_reason("x", "parse_changed") == "PARSE_CHANGED"
    assert classify_zero_reason("x", "timeout") == "TIMEOUT"
    assert classify_zero_reason("x", "not_configured") == "NOT_CONFIGURED"
    assert classify_zero_reason("x", "no_public_client_feed") == "NO_PUBLIC_FEED"


def test_source_yield_score():
    from sources.source_health import record_source_run, compute_source_yield_score
    # Healthy source with jobs
    record_source_run("healthy_src", "success", jobs_count=10)
    score = compute_source_yield_score("healthy_src")
    assert score > 50
    # Blocked source
    for _ in range(5):
        record_source_run("blocked_src", "blocked")
    score = compute_source_yield_score("blocked_src")
    assert score < 50


def test_egypt_registry_expanded():
    from sources.egypt_employer_registry import EGYPT_EMPLOYERS, validate_employer_registry
    assert len(EGYPT_EMPLOYERS) >= 30
    validate_employer_registry()  # Should not raise


def test_arab_careers_specs_have_urls():
    from sources.arab_careers import _ARAB_COMPANY_SPECS
    for spec in _ARAB_COMPANY_SPECS:
        assert spec["url"].startswith("https://")
        assert spec["geo_hint"] in ("arab", "egypt", "gulf")


def test_zero_sources_report():
    from sources.source_health import record_source_run, get_zero_sources_report
    record_source_run("empty_src", "empty")
    report = get_zero_sources_report()
    empty_entries = [r for r in report if r["source"] == "empty_src"]
    assert len(empty_entries) == 1
    assert empty_entries[0]["reason"] == "EMPTY_REAL"
