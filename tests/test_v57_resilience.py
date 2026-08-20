"""Regression coverage for the bounded-run, review, and integrity controls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _job(title: str, *, source: str = "linkedin_unified", company: str = "Acme", probability: float = 0.7):
    from models import CyberVerdict, Job

    row = Job(
        title=title,
        company=company,
        location="Cairo, Egypt",
        url=f"https://example.com/{hashlib.sha1((title + source + company).encode()).hexdigest()}",
        description="Cybersecurity role",
        source=source,
    )
    row.source_key = source
    row.cyber_verdict = CyberVerdict.LIKELY.value
    row.cyber_probability = probability
    row.filter_reason = "likely_keyword_context"
    return row


@pytest.mark.parametrize(
    "title",
    [
        "IT Security Specialist",
        "Network Security BackOffice Engineer",
        "Senior Security Operation Engineer",
        "Access Management - Ping / Okta Engineer",
    ],
)
def test_requested_borderline_titles_have_explicit_cyber_patterns(title):
    from intelligence.intent import classify_cyber_intent

    result = classify_cyber_intent(_job(title))
    assert result.accept, f"{title} must enter the cyber pipeline"


def test_egypt_registry_enforces_linkedin_and_verified_careers_url():
    from sources.egypt_employer_registry import EGYPT_EMPLOYERS, validate_employer_registry

    validate_employer_registry()
    assert EGYPT_EMPLOYERS
    assert all(row.linkedin_identifier and row.careers_url.startswith("https://") for row in EGYPT_EMPLOYERS)


def test_stratified_review_sampling_uses_full_quota_when_diversity_is_limited():
    from review_workflow import _sample_stratified

    rows = [_job(f"Security Engineer {index}", source="single_source", company="Single Co") for index in range(12)]
    sample = _sample_stratified(rows, quota=8, seed="run")
    assert len(sample) == 8
    # The summed inverse-probability weights recover the 12-row population.
    assert sum(weight for _, weight in sample) == pytest.approx(12.0)


def test_model_manifest_mismatch_fails_closed(tmp_path: Path, monkeypatch):
    import ml_filter

    artifact = tmp_path / "model.joblib"
    artifact.write_bytes(b"approved-model")
    manifest = tmp_path / "model.manifest.json"
    manifest.write_text(json.dumps({
        "sklearn_version": "1.9.0",  # intentionally incompatible
        "feature_schema_version": "cyber-job-features-v1",
        "feature_schema_hash": ml_filter.feature_schema_hash(),
        "model_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }), encoding="utf-8")
    monkeypatch.setattr(ml_filter, "_SKLEARN_READY", True)
    monkeypatch.setattr(ml_filter, "sklearn", SimpleNamespace(__version__="1.8.0"), raising=False)
    monkeypatch.setattr(ml_filter.config, "ML_MODEL_MANIFEST_PATH", str(manifest))

    with pytest.raises(ml_filter.ModelIntegrityError, match="sklearn mismatch"):
        ml_filter._AdaptiveLocalCyberClassifier(str(artifact))._load_from_disk()


def test_failed_endpoint_opens_a_run_local_circuit(monkeypatch):
    import requests
    from run_budget import start_run
    from sources import http_utils

    calls = []

    def fail_once(*args, **kwargs):
        calls.append((args, kwargs))
        raise requests.ConnectionError("target offline")

    start_run(30)
    http_utils.reset_http_run_state()
    monkeypatch.setattr(http_utils._session, "request", fail_once)
    assert http_utils.get_text_result("https://example.invalid/jobs", use_proxy=False).text is None
    assert http_utils.get_text_result("https://example.invalid/jobs", use_proxy=False).text is None
    assert len(calls) == 1
    assert http_utils.get_http_metrics()["endpoint_circuit_open"] >= 1


def test_proxy_402_uses_one_direct_bypass(monkeypatch):
    from run_budget import start_run
    from sources import http_utils

    class Response:
        def __init__(self, status_code: int, text: str = ""):
            self.status_code = status_code
            self.text = text

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("http failure")

    calls = []

    def request(*args, **kwargs):
        calls.append(kwargs.get("proxies"))
        return Response(402) if len(calls) == 1 else Response(200, "direct fallback")

    start_run(30)
    http_utils.reset_http_run_state()
    monkeypatch.setattr(http_utils._proxy_pool, "_proxies", ["http://proxy.example:8080"])
    monkeypatch.setattr(http_utils._proxy_pool, "_scores", {"http://proxy.example:8080": 50.0})
    monkeypatch.setattr(http_utils._session, "request", request)
    result = http_utils.get_text_result("https://target.example/jobs")

    assert result.text == "direct fallback"
    assert len(calls) == 2
    assert calls[1] == {}
    metrics = http_utils.get_http_metrics()
    assert metrics["402"] == 1
    assert metrics["direct_bypass"] == 1


def test_http_layer_honors_the_other_sources_phase_before_a_request(monkeypatch):
    from run_budget import start_phase, start_run
    from sources import http_utils

    calls = []
    start_run(30)
    start_phase("other_sources", 0)
    http_utils.reset_http_run_state()
    monkeypatch.setattr(http_utils._session, "request", lambda *a, **k: calls.append((a, k)))

    result = http_utils.get_text_result("https://example.invalid/jobs", use_proxy=False)

    assert result.text is None
    assert result.error_code == "run_budget_exhausted"
    assert not calls


def test_linkedin_pagination_expands_only_to_its_configured_cap(monkeypatch):
    from sources.linkedin_unified import QuerySpec, _expanded_pages
    import config

    monkeypatch.setattr(config, "LINKEDIN_MAX_PAGES_PER_QUERY", 6)
    assert _expanded_pages(QuerySpec("SOC", pages=(0, 25))) == (0, 25, 50, 75, 100, 125)


def test_fetch_runner_uses_a_bounded_executor_without_asyncio_run(monkeypatch):
    import main

    async def fake_fetch(stats, db, reports):
        return ["completed-before-executor-cleanup"]

    monkeypatch.setattr(main, "fetch_all_async", fake_fetch)
    assert main.run_fetch_all({}, object(), {}) == ["completed-before-executor-cleanup"]


def test_fetch_runner_returns_at_source_budget_when_a_sync_source_is_stuck(monkeypatch):
    import time

    import main
    from run_budget import start_phase, start_run
    from sources.source_registry import SourceSpec

    def slow_source():
        time.sleep(0.25)
        return []

    monkeypatch.setattr(main, "get_source_specs", lambda: [
        SourceSpec("slow_source", "Slow source", slow_source, 100, "test"),
    ])
    monkeypatch.setattr(main, "_source_enabled_by_health", lambda spec, db: True)
    start_run(5)
    start_phase("other_sources", 0.03)

    started = time.monotonic()
    assert main.run_fetch_all({}, object(), {}) == []
    assert time.monotonic() - started < 0.15


def test_description_only_cloud_product_mention_cannot_route_to_cloudsec():
    from intelligence.domain import classify_domain, has_channel_evidence
    from telegram_sender import _topic_channel_for_job

    job = _job("Solutions Engineer, Growth - East")
    job.description = "Help customers adopt cloud security products, CSPM, and CNAPP."

    # Broad classification may identify the product domain for ranking, but
    # channel delivery requires cyber evidence in the role/title or tags.
    assert classify_domain(job) == "cloudsec"
    assert not has_channel_evidence(job, "cloudsec")
    assert _topic_channel_for_job(job, "") is None


def test_explicit_cloud_security_role_routes_to_cloudsec():
    from intelligence.domain import has_channel_evidence
    from telegram_sender import _topic_channel_for_job

    job = _job("Cloud Security Engineer")
    job.description = "Build CSPM controls for AWS and Azure workloads."

    assert has_channel_evidence(job, "cloudsec")
    assert _topic_channel_for_job(job, "") == "cloudsec"


def test_non_cyber_and_generic_likely_roles_cannot_enter_telegram():
    from models import CyberVerdict
    from telegram_sender import _is_telegram_eligible

    non_cyber = _job("Deal Desk Analyst")
    non_cyber.cyber_verdict = CyberVerdict.NON_CYBER.value
    assert not _is_telegram_eligible(non_cyber)

    generic_likely = _job("Solutions Support Engineer")
    generic_likely.description = "Help customers adopt AWS, Python, and cloud products."
    assert not _is_telegram_eligible(generic_likely)

    # v62 verdict consistency: a CYBER_CONFIRMED row with a valid delivery
    # location and an exact posting identity is trusted at delivery and is
    # never re-rejected by the evidence gate.  The upstream classifier is the
    # only authority that can produce such a row for a generic title.
    confirmed_erp_admin = _job("NetSuite Administrator")
    confirmed_erp_admin.cyber_verdict = CyberVerdict.CONFIRMED.value
    confirmed_erp_admin.description = "ERP administration, user provisioning, and reports."
    assert _is_telegram_eligible(confirmed_erp_admin)

    confirmed_without_location = _job("NetSuite Administrator")
    confirmed_without_location.cyber_verdict = CyberVerdict.CONFIRMED.value
    confirmed_without_location.location = "London, UK"
    assert not _is_telegram_eligible(confirmed_without_location)


def test_cloudsec_requires_explicit_cloud_security_evidence():
    from intelligence.domain import has_channel_evidence

    vague = _job("Solutions Engineer")
    vague.description = "Use AWS, Python, and cloud products with customers."
    assert not has_channel_evidence(vague, "cloudsec")

    explicit = _job("Cloud Security Engineer")
    explicit.description = "Implement CWPP and cloud threat detection for Kubernetes."
    assert has_channel_evidence(explicit, "cloudsec")


def test_requested_source_order_keeps_linkedin_first():
    import config

    assert config.source_priority("linkedin_unified") < config.source_priority("company_careers")
    assert config.source_priority("company_careers") < config.source_priority("greenhouse_cybersec")
    assert config.source_priority("greenhouse_cybersec") < config.source_priority("indeed")
    assert config.source_priority("indeed") < config.source_priority("wuzzuf")


def test_arab_focus_rotation_covers_every_arab_country_with_soc_pentest_emphasis():
    from math import ceil
    from sources.linkedin_unified import ARAB_COUNTRY_LOCATIONS, _arab_focus_queries

    selected_locations = set()
    for slot in range(ceil(len(ARAB_COUNTRY_LOCATIONS) / 5)):
        queries = _arab_focus_queries(slot)
        assert len(queries) == 5
        assert sum(q.keywords in {"SOC analyst", "penetration tester"} for q in queries) == 4
        assert all(q.source_key == "linkedin_arab" for q in queries)
        selected_locations.update(q.location for q in queries)

    assert selected_locations == set(ARAB_COUNTRY_LOCATIONS)


def test_exact_dedup_retains_same_title_and_company_when_urls_differ(monkeypatch):
    import dedup
    from models import Job

    class EmptyHistory:
        def was_sent_globally_recently(self, *args, **kwargs):
            return False

        def was_sent_recently(self, *args, **kwargs):
            return False

    monkeypatch.setattr(dedup, "_db", EmptyHistory())
    first = Job("SOC Analyst", "Acme", "Cairo, Egypt", "https://jobs.example.com/101", "linkedin")
    second = Job("SOC Analyst", "Acme", "Cairo, Egypt", "https://jobs.example.com/202", "linkedin")

    assert dedup.deduplicate([first, second], {}) == [first, second]


def test_cyber_gate_runs_before_location_gate(monkeypatch):
    from datetime import datetime

    import config
    from models import CyberVerdict, Job, classify_jobs

    monkeypatch.setattr(config, "ML_FILTER_ENABLED", False)
    job = Job(
        "Cybersecurity Engineer", "Acme", "London, UK", "https://jobs.example.com/uk-security", "test",
        description="Security engineering, vulnerability management, and threat detection.",
        posted_date=datetime.now(),
    )
    accepted, rejected = classify_jobs([job])

    assert accepted == []
    assert rejected == [job]
    assert job.cyber_verdict == CyberVerdict.CONFIRMED.value
    assert job.filter_reason == "reject_geo_filter"


def test_protected_telegram_phase_survives_an_upstream_total_budget_overrun(monkeypatch):
    import run_budget

    clock = {"now": 100.0}
    monkeypatch.setattr(run_budget.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        run_budget, "_CURRENT", run_budget.RunBudget(total_seconds=10, started_at=clock["now"])
    )
    run_budget.start_phase("telegram", 50, protected=True)
    clock["now"] = 111.0  # total deadline has expired

    assert run_budget.remaining() == 0
    assert run_budget.remaining("telegram") == 39


def test_job_message_uses_the_compact_professional_card_layout():
    from datetime import datetime, timedelta

    from telegram_sender import format_job_message

    job = _job("Access Management - Ping / Okta Engineer", company="Accenture")
    job.location = "Cairo, Cairo Governorate, Egypt"
    job.job_type = "Full-time"
    job.posted_date = datetime.now() - timedelta(hours=2)
    job.tags = ["Ping Identity", "Okta", "IAM", "Identity Security"]
    # v76: skills on the card come from source-backed canonical evidence
    # attached by the enrichment layer (never re-extracted from free text).
    job.skills_with_evidence = {
        "Ping Identity": ["Ping Identity"],
        "Okta": ["Okta"],
        "Identity Security": ["Identity Security"],
        "IAM": ["iam"],
    }
    message = format_job_message(job)

    # v77: the card follows the user-requested template — domain header,
    # title line, then labeled detail lines (Company/Location/Level/Posted/
    # Type), a "Key Skills" bulleted block, and the source/apply footer.
    # Header category comes from the canonical primary_category when present;
    # without enrichment the card keeps the legacy Security Engineering.
    has_header = (
        message.startswith("🛡️ <b>Security Engineering</b>")
        or message.startswith("🔑 <b>IAM / Access Security</b>")
    )
    assert has_header
    assert "🔐 <b>Access Management - Ping / Okta Engineer</b>" in message
    assert "🏢 <b>Company:</b> Accenture" in message
    assert "📍 <b>Location:</b> Cairo, Cairo Governorate, Egypt" in message
    assert "🕒 <b>Posted:</b> 2 hours ago" in message
    assert "📌 <b>Type:</b> Full-time" in message
    assert "<b>Level:</b> Mid-Level" in message
    # v76/v77: skills appear as a "Key Skills" bulleted block from the
    # source-backed canonical evidence — never re-extracted from free text.
    assert "<b>Key Skills</b>" in message
    for skill in ("Ping Identity", "Okta", "Identity Security", "IAM"):
        assert f"• {skill}" in message
    assert "Source:" in message and "LinkedIn" in message
    assert '<a href="https://example.com/' in message
    assert "🚀 Apply Now →</a>" in message
    assert message.index("Source:") < message.index("🚀 Apply Now →</a>")
    assert "Match Strength" not in message


def test_card_skills_never_invented_without_canonical_evidence():
    """v76: when no source-backed skills exist, the card has no skills line —
    it never falls back to a guessed 'Cybersecurity' keyword."""
    from telegram_sender import format_job_message

    job = _job("Access Management - Ping / Okta Engineer", company="Accenture")
    job.skills_with_evidence = {}
    message = format_job_message(job)

    assert "⚙️" not in message, "skills line must not be rendered without evidence"
