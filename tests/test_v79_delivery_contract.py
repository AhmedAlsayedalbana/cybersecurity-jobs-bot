"""v79 end-to-end delivery-contract tests (senior-grade precision suite).

Locks the full pipeline path filter → pool → route exactly as production
runs it, plus the v79 contracts:
  * 48h hard recency (nothing older than two days is ever sent)
  * Egypt → Arab → Remote geo priority, no duplicates
  * 70/30 LinkedIn split per topic channel; Egypt/Gulf uncapped
  * Tier-4 internship precision: senior GRC roles NEVER leak to internships
  * remote_feeds per-feed isolation
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config
from models import Job, is_recent_enough


def _job(title, *, location="Cairo, Egypt", source="linkedin_unified",
         description="cybersecurity soc siem splunk firewall threat detection incident response",
         hours_ago=5, company="Acme", url=None):
    return Job(
        title=title, company=company, location=location,
        url=url or f"https://example.com/{abs(hash(title)) % 10**8}",
        source=source, source_key=source, description=description,
        content_type="job_listing",
        posted_date=datetime.now() - timedelta(hours=hours_ago),
    )


# ── Tier-4 internship precision (the reported GRC→internships bug) ──────────

def test_senior_grc_specialist_never_routes_to_internships():
    from telegram_sender import route_job
    job = _job(
        "Specialist Data And Access Security Planning",
        location="Dubai, UAE", source="linkedin_arab",
        description=("Data access security planning IAM compliance GRC. "
                     "Requires 0-2 years experience in security operations. "
                     "SIEM Splunk firewall threat detection."),
    )
    channels = route_job(job)
    # The leak is fixed: never internships. Geo must hold (gulf). The grc
    # topic itself additionally requires publish-grade evidence (v62
    # contract), which a thin synthetic description does not carry — so the
    # assertion here is no-leak + geo-preserved, not topic-forced.
    assert "internships" not in channels
    assert "gulf" in channels


def test_true_intern_still_routes_to_internships():
    from telegram_sender import route_job
    job = _job(
        "Cybersecurity Intern",
        description=("Cybersecurity internship program for students. Learn SOC "
                     "SIEM Splunk incident response threat hunting."),
    )
    assert "internships" in route_job(job)


def test_junior_pentest_still_routes_to_internships():
    from telegram_sender import route_job
    job = _job(
        "Junior Penetration Tester",
        description=("Junior pentest role. ethical hacking bug bounty OSCP "
                     "training provided. penetration testing red team."),
    )
    assert "internships" in route_job(job)


def test_senior_soc_lead_with_graduate_boilerplate_is_not_internship():
    from intelligence.intent import is_true_security_internship
    job = _job(
        "Senior SOC Analyst",
        description=("Lead SOC operations, SIEM Splunk Sentinel incident response. "
                     "Our graduate scheme welcomes applicants. 0-2 years experience ok."),
    )
    assert not is_true_security_internship(job)


# ── 48h hard recency ─────────────────────────────────────────────────────────

def test_nothing_older_than_two_days_passes_recency():
    old = _job("SOC Analyst", hours_ago=49)
    ok, reason = is_recent_enough(old, max_age_hours=config.MAX_JOB_AGE_HOURS)
    assert not ok
    assert config.MAX_JOB_AGE_HOURS == 48
    fresh = _job("SOC Analyst", hours_ago=47)
    assert is_recent_enough(fresh, max_age_hours=config.MAX_JOB_AGE_HOURS)[0]


# ── Geo priority + routing matrix ────────────────────────────────────────────

def test_egypt_grc_routes_egypt_and_grc_only():
    from telegram_sender import route_job
    job = _job("GRC Consultant", location="Cairo, Egypt",
               description="GRC compliance ISO 27001 risk audit cybersecurity governance.")
    assert route_job(job) == ["egypt", "grc"]


def test_gulf_soc_routes_gulf_and_soc():
    from telegram_sender import route_job
    job = _job("SOC Analyst", location="Riyadh, Saudi Arabia", source="linkedin_arab")
    assert route_job(job) == ["gulf", "soc"]


def test_remote_networksec_routes_remote_only_v80():
    # v80: foreign/remote jobs go to Remote ONLY, never topic channels —
    # even with a perfect specialty match.
    from telegram_sender import route_job
    job = Job(
        title="Network Security Engineer", company="X", location="Remote",
        url="https://example.com/r1", source="greenhouse_expanded",
        source_key="greenhouse_expanded",
        description="Network security firewall Palo Alto zero trust IDS IPS.",
        content_type="job_listing", is_remote=True,
        posted_date=datetime.now() - timedelta(hours=3),
    )
    assert route_job(job) == ["remote"]


# ── Pool: 70% LI cap, focus domains, Egypt-first ─────────────────────────────

def test_pool_linkedin_share_never_exceeds_70_percent():
    from intelligence.pool_builder import build_final_pool
    jobs = (
        [_job(f"SOC Analyst {i}", source="linkedin_unified", hours_ago=2) for i in range(60)]
        + [_job(f"Threat Hunter {i}", source="wuzzuf", hours_ago=2) for i in range(60)]
    )
    pool = build_final_pool(jobs, lambda j: 20)
    li = sum(1 for j in pool if "linkedin" in (j.source_key or j.source))
    assert li <= round(len(pool) * config.LINKEDIN_POOL_CAP_RATIO) + 1
    assert config.LINKEDIN_POOL_CAP_RATIO == 0.70


def test_pool_orders_egypt_before_remote_within_freshness():
    from intelligence.pool_builder import build_final_pool
    jobs = [
        _job("Cloud Sec R", location="Remote", source="greenhouse_expanded", hours_ago=5),
        _job("Cloud Sec E", location="Cairo, Egypt", source="greenhouse_expanded", hours_ago=5),
    ]
    pool = build_final_pool(jobs, lambda j: 20)
    assert pool[0].location == "Cairo, Egypt"


def test_pool_prefers_focus_domains_soc_over_generic():
    from intelligence.pool_builder import build_final_pool
    jobs = [
        _job("Security Engineer G", location="Remote", source="greenhouse_expanded",
             description="cybersecurity engineer firewall VPN support", hours_ago=5),
        _job("SOC Analyst F", location="Remote", source="greenhouse_expanded",
             description="SOC analyst SIEM Splunk incident response threat hunting", hours_ago=5),
    ]
    pool = build_final_pool(jobs, lambda j: 20)
    assert pool[0].title == "SOC Analyst F"


# ── remote_feeds isolation ───────────────────────────────────────────────────

def test_remote_feeds_isolates_dead_feed(monkeypatch):
    import sources.remote_feeds as rf

    good = _job("SOC Analyst", location="Remote", source="remoteok", hours_ago=3)

    monkeypatch.setattr(rf, "_FEEDS", (
        ("dead", lambda: (_ for _ in ()).throw(RuntimeError("boom"))),
        ("ok", lambda: [good]),
    ))
    result = rf.fetch_remote_feeds()
    assert result.status == "success"
    assert len(result.jobs) == 1
    assert result.jobs[0].source_key == "remote_feeds"


def test_remote_feeds_honest_empty_when_all_answer_blank(monkeypatch):
    import sources.remote_feeds as rf
    monkeypatch.setattr(rf, "_FEEDS", (("a", lambda: []), ("b", lambda: [])))
    result = rf.fetch_remote_feeds()
    assert result.status == "empty"


# ── v80: remote-only topics, 10/15 caps, Arab-only topic gate ───────────────

def test_topic_channels_reject_remote_jobs_at_send_gate():
    from intelligence.geo import validate_location_for_channel
    job = _job("SOC Analyst", location="Remote", source="greenhouse_expanded",
               description="SOC analyst SIEM Splunk incident response")
    job.is_remote = True
    for topic in ("soc", "pentest", "appsec", "cloudsec", "grc", "seceng",
                  "networksec", "internships"):
        assert not validate_location_for_channel(job, topic)[0]
    assert validate_location_for_channel(job, "remote")[0]


def test_arab_jobs_pass_topic_gate():
    from intelligence.geo import validate_location_for_channel
    job = _job("SOC Analyst", location="Riyadh, Saudi Arabia", source="linkedin_arab")
    assert validate_location_for_channel(job, "soc")[0]
    assert validate_location_for_channel(job, "gulf")[0]
    assert not validate_location_for_channel(job, "egypt")[0]


def test_channel_caps_10_and_remote_15():
    assert config.MAX_JOBS_PER_CHANNEL == 10
    assert config.MAX_JOBS_REMOTE_CHANNEL == 15
    assert config.TELEGRAM_SEND_DELAY == 3


def test_70_30_slot_math_per_cap():
    for cap, li, non in ((10, 7, 3), (15, 11, 4)):
        assert max(1, int(cap * 0.70 + 0.5)) == li
        assert cap - max(1, int(cap * 0.70 + 0.5)) == non


def test_make_job_never_fakes_now():
    from sources.egypt_boards import _make_job
    job = _make_job(title="SOC Analyst", company="X", location="Cairo",
                    url="https://example.com/x", source="wazzif")
    assert job is not None
    assert job.posted_date is None


def test_eg_linkedin_companies_lane_registered_as_linkedin():
    from sources.source_registry import get_source_specs
    specs = {s.key: s for s in get_source_specs()}
    assert "eg_linkedin_companies" in specs
    assert config.source_priority("eg_linkedin_companies") == 12


# ── Registry hygiene: dead specs gone, bundle present ────────────────────────

def test_dead_specs_removed_and_bundle_registered():
    from sources.source_registry import get_source_specs
    keys = {s.key for s in get_source_specs()}
    for dead in ("upwork", "mostaql", "contra", "fiverr", "khamsat", "toptal"):
        assert dead not in keys
    assert "remote_feeds" in keys
    assert "freelancer" in keys and "wuzzuf" in keys


def test_source_priority_orders_egypt_arab_foreign():
    assert config.source_priority("linkedin_unified") == 10
    assert config.source_priority("wuzzuf") < config.source_priority("bayt")
    assert config.source_priority("bayt") < config.source_priority("indeed")
    assert config.source_priority("indeed") < config.source_priority("greenhouse")
    assert config.source_priority("greenhouse") < config.source_priority("remote_feeds")
