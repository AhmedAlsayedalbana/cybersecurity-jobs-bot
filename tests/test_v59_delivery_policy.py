"""Acceptance regressions for strict delivery location/evidence/timeouts."""

from __future__ import annotations

from datetime import datetime
import time

import pytest

from models import CyberVerdict, Job


def _job(title: str, location: str, *, job_type: str = "", remote: bool = False) -> Job:
    job = Job(
        title=title,
        company="Acme Security",
        location=location,
        url=f"https://jobs.example.com/{title.lower().replace(' ', '-')}",
        source="linkedin_unified",
        source_key="linkedin_unified",
        description="Cybersecurity role with security controls.",
        posted_date=datetime.now(),
        job_type=job_type,
        is_remote=remote,
    )
    job.cyber_verdict = CyberVerdict.CONFIRMED.value
    return job


@pytest.mark.parametrize(
    ("title", "location", "channel"),
    [
        ("Security Engineer (Bangkok Based, Relocation)", "Cairo, Egypt", "egypt"),
        ("Security Engineer", "Mexico City, Mexico", "gulf"),
        ("Security Engineer", "New York, USA", "egypt"),
    ],
)
def test_outside_region_physical_roles_are_never_deliverable(title, location, channel):
    from intelligence.geo import resolve_delivery_location, validate_location_for_channel
    from telegram_sender import route_job

    job = _job(title, location)
    accepted, decision = validate_location_for_channel(job, channel)

    assert not accepted
    assert decision.reason_code == "physical_outside_region"
    assert decision.location_type == "physical"
    assert channel not in route_job(job)
    assert not route_job(job)  # no geo or specialty Telegram leakage


@pytest.mark.parametrize(
    ("location", "job_type", "channel"),
    [
        ("Cairo, Egypt", "", "egypt"),
        ("Riyadh, Saudi Arabia", "Hybrid", "gulf"),
        ("Dubai, UAE", "Hybrid", "gulf"),
    ],
)
def test_egypt_and_all_arab_physical_hybrid_locations_are_allowed(location, job_type, channel):
    from intelligence.geo import validate_location_for_channel

    accepted, decision = validate_location_for_channel(_job("Security Engineer", location, job_type=job_type), channel)

    assert accepted
    assert decision.geo == ("egypt" if channel == "egypt" else "arab")
    assert decision.location_type == ("hybrid" if job_type else "physical")


def test_explicit_worldwide_remote_stays_remote_despite_company_country():
    from intelligence.geo import validate_location_for_channel
    from telegram_sender import route_job

    job = _job("SOC Analyst — Remote", "New York, USA", remote=True)
    accepted, decision = validate_location_for_channel(job, "remote")

    assert accepted
    assert decision.geo == "remote"
    assert decision.reason_code == "remote_worldwide"
    assert "remote" in route_job(job)
    assert "soc" in route_job(job)


def test_unknown_physical_location_is_blocked_without_query_hint():
    from intelligence.geo import validate_location_for_channel

    job = _job("Security Engineer", "Not specified")
    job.geo_hint = "arab"
    accepted, decision = validate_location_for_channel(job, "gulf")

    assert not accepted
    assert decision.reason_code == "unknown_location"
    assert decision.location_type == "unknown"


@pytest.mark.parametrize(
    "title",
    [
        "Vulnerability Management Analyst", "IAM Engineer", "IGA - Saviynt Engineer",
        "SOC Analyst", "Application Security Engineer", "Pentest Consultant",
    ],
)
def test_explicit_cyber_domain_titles_have_publishable_evidence(title):
    from telegram_sender import _publishable_cyber_evidence

    evidence, missing = _publishable_cyber_evidence(_job(title, "Cairo, Egypt"))

    assert evidence == "title_cyber_evidence"
    assert not missing


@pytest.mark.parametrize("title", ["Solutions Engineer", "Solutions Support Engineer", "Support Engineer"])
def test_generic_solutions_support_titles_remain_insufficient_evidence(title):
    from telegram_sender import _publishable_cyber_evidence

    job = _job(title, "Cairo, Egypt")
    job.description = "Help customers adopt AWS, Python, and cloud products."
    evidence, missing = _publishable_cyber_evidence(job)

    assert evidence == "insufficient_cyber_evidence"
    assert "explicit_title_or_domain" in missing


def test_source_timeout_isolates_slow_cib_and_still_runs_amazon(monkeypatch):
    """A slow browser-like source cannot consume the full other-sources phase."""
    import config
    import main
    from run_budget import start_phase, start_run
    from sources.source_registry import SourceSpec

    started: list[str] = []

    def slow_cib():
        started.append("cib")
        time.sleep(0.20)
        return []

    def amazon():
        started.append("amazon")
        return []

    specs = [
        SourceSpec("cib", "CIB Careers", slow_cib, 20, "core", source_timeout_seconds=0.04),
        SourceSpec("amazon", "Amazon AWS Careers", amazon, 21, "core", source_timeout_seconds=0.04),
    ]
    monkeypatch.setattr(main, "get_source_specs", lambda: specs)
    monkeypatch.setattr(main, "_source_enabled_by_health", lambda spec, db: True)
    start_run(2)
    start_phase("other_sources", 0.30)
    reports: dict[str, dict] = {}

    started_at = time.monotonic()
    assert main.run_fetch_all({}, object(), reports) == []

    assert time.monotonic() - started_at < 0.14
    assert "amazon" in started
    assert reports["cib"]["status"] == "timeout"
    assert reports["cib"]["cancelled_by_source_deadline"] is True
    assert reports["amazon"]["source_timeout"] is False


def test_dry_run_executes_router_without_calling_telegram(monkeypatch):
    """The first-run preview must validate queues without network/persistence."""
    import telegram_sender

    class ReadOnlyDB:
        def was_sent_to_channel_recently(self, **_kwargs):
            return False

    monkeypatch.setattr(telegram_sender, "get_db", lambda: ReadOnlyDB())
    monkeypatch.setattr(
        telegram_sender,
        "_send_to_topic",
        lambda *_args, **_kwargs: pytest.fail("DRY_RUN must never post to Telegram"),
    )

    count, records = telegram_sender.send_jobs(
        [_job("Security Engineer", "Cairo, Egypt")],
        dry_run=True,
    )

    assert count == 2  # Egypt + explicit Security Engineering specialty route
    assert {channel for _, _, channel in records} == {"egypt", "seceng"}
