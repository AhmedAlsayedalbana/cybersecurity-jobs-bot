"""Regression coverage for delivery location and fresh-first ordering."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from intelligence.domain import has_channel_evidence
from intelligence.geo import classify_delivery_geo, classify_geo, is_remote_job
from intelligence.pool_builder import build_final_pool, freshness_sort_key
from models import CyberVerdict, Job, passes_geo_filter
from telegram_sender import _is_telegram_eligible, route_job


def _job(
    title: str = "Cybersecurity Engineer",
    *,
    location: str = "Cairo, Egypt",
    description: str = "Build security controls and threat detection.",
    is_remote: bool = False,
    geo_hint: str = "",
    posted_date: datetime | None = None,
) -> Job:
    job = Job(
        title=title,
        company="Acme",
        location=location,
        url=f"https://example.com/{title.lower().replace(' ', '-')}-{location.lower().replace(' ', '-')}",
        source="linkedin_unified",
        source_key="linkedin_unified",
        description=description,
        is_remote=is_remote,
        geo_hint=geo_hint,
        posted_date=posted_date or datetime.now(),
    )
    job.cyber_verdict = CyberVerdict.CONFIRMED.value
    return job


def test_explicit_remote_role_with_egypt_office_location_routes_only_remote():
    job = _job(title="Cyber Security Analyst (Remote)", location="Cairo, Egypt")

    assert is_remote_job(job)
    assert classify_geo(job) == "remote"
    assert route_job(job)[0] == "remote"
    assert "egypt" not in route_job(job)


def test_global_physical_job_is_accepted_for_remote_discovery():
    # v78: Global physical jobs are now accepted to feed the remote channel.
    job = _job(location="London, United Kingdom", geo_hint="egypt")

    assert classify_geo(job) == "global"
    assert passes_geo_filter(job)
    assert _is_telegram_eligible(job)
    assert "remote" in route_job(job)
    # v78: specialty channels (like soc/pentest) are now permitted for global jobs
    # if the role proves cyber relevance, acting as discovery for the remote channel.
    # We only assert that they DON'T go to regional geo channels.
    assert "egypt" not in route_job(job)
    assert "gulf" not in route_job(job)


def test_global_hybrid_job_is_accepted_for_remote_discovery():
    job = _job(location="Berlin, Germany", is_remote=True)
    job.job_type = "Hybrid"

    assert not is_remote_job(job)
    assert classify_geo(job) == "global"
    assert passes_geo_filter(job)
    assert "remote" in route_job(job)
    assert "egypt" not in route_job(job)
    assert "gulf" not in route_job(job)


def test_unknown_physical_location_is_accepted_for_remote_discovery():
    job = _job(location="Not specified", geo_hint="arab")

    assert classify_geo(job) == "arab"  # discovery telemetry only
    assert classify_delivery_geo(job) == "global"
    assert passes_geo_filter(job)
    assert "remote" in route_job(job)
    assert "egypt" not in route_job(job)
    assert "gulf" not in route_job(job)


def test_training_job_cannot_route_to_soc_from_description_only_signal():
    job = _job(
        title="Undergrad Cybersecurity Instructor",
        location="Riyadh, Saudi Arabia",
        description="Teach SOC analysis, SIEM monitoring, threat hunting, and incident response.",
    )

    assert not has_channel_evidence(job, "soc")
    assert route_job(job) == ["gulf"]


def test_freshness_key_orders_known_recent_jobs_before_old_and_unknown():
    now = datetime.now()
    fresh = _job(posted_date=now - timedelta(minutes=20))
    old = _job(posted_date=now - timedelta(hours=20))
    unknown = _job()
    unknown.posted_date = None

    assert freshness_sort_key(fresh, now=now) < freshness_sort_key(old, now=now)
    assert freshness_sort_key(old, now=now) < freshness_sort_key(unknown, now=now)


def test_final_pool_uses_freshness_before_source_rank(monkeypatch: pytest.MonkeyPatch):
    import config

    now = datetime.now()
    old_linkedin = _job(location="Cairo, Egypt", posted_date=now - timedelta(hours=20))
    old_linkedin.origin_priority = 10
    fresh_board = _job(location="Cairo, Egypt", posted_date=now - timedelta(minutes=15))
    fresh_board.source = "wuzzuf"
    fresh_board.source_key = "wuzzuf"
    fresh_board.origin_priority = 90

    monkeypatch.setattr(config, "MAX_JOBS_PER_RUN", 2)
    monkeypatch.setattr(config, "SCORE_THRESHOLD", 0)
    monkeypatch.setattr(config, "NON_LINKEDIN_POOL_FLOOR_RATIO", 0.0)
    monkeypatch.setattr(config, "ENTRY_LEVEL_TARGET_RATIO", 0.0)
    monkeypatch.setattr(config, "LINKEDIN_POOL_CAP_RATIO", 1.0)

    pool = build_final_pool([old_linkedin, fresh_board], score_fn=lambda _: 20)

    assert pool[0] is fresh_board
