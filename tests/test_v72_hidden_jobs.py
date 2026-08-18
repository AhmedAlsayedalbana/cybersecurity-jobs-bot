"""v72 regression tests — Hidden Jobs Discovery + Personal Opportunity Score.

Baseline preserved: no existing gate is relaxed by either feature.
"""
import time
import tempfile
import os
from unittest import mock

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in __import__("sys").path:
    __import__("sys").path.insert(0, BASE_DIR)


# ── Hiring signal detection ────────────────────────────────────────────────

def test_detect_hiring_signal_positive():
    from sources.hiring_signal_discovery import detect_hiring_signal

    post = (
        "We're growing our security team at Vodafone in Cairo! "
        "Looking for SOC analysts and pentesters to join us. DM me."
    )
    signal = detect_hiring_signal(post)
    assert signal is not None
    assert signal.company == "Vodafone"
    assert signal.inferred_title.lower() in ("soc analyst", "pentest",
                                             "penetration testing")


def test_detect_hiring_signal_requires_company_role_and_growth():
    from sources.hiring_signal_discovery import detect_hiring_signal

    assert detect_hiring_signal(
        "We're growing our security team! DM me.") is None  # no company
    assert detect_hiring_signal(
        "Vodafone is hiring for a new SOC analyst role soon.") is None  # no growth phrase
    assert detect_hiring_signal(
        "Vodafone is hiring front-end devs in Cairo.") is None        # no cyber role
    assert detect_hiring_signal("") is None


def test_detect_hiring_signal_skips_generic_it():
    from sources.hiring_signal_discovery import detect_hiring_signal

    # A plain non-security role mention must never become a signal — the
    # gate requires explicit cyber intent.
    assert detect_hiring_signal(
        "Vodafone is hiring helpdesk support engineers in Cairo.") is None


# ── Verification chain ─────────────────────────────────────────────────────

def test_verify_signal_found_application_url():
    from sources.hiring_signal_discovery import (
        detect_hiring_signal, verify_signal, _reset_v72_telemetry,
    )
    _reset_v72_telemetry()
    signal = detect_hiring_signal(
        "We're growing our security team at Wiz. Join us as a security "
        "engineer!")
    assert signal is not None

    def search_fn(spec):
        if spec["kind"] == "linkedin_jobs":
            return [("https://www.linkedin.com/jobs/view/123",
                     "Security Engineer at Wiz")]
        return []

    def builder(url, title, company):
        from models import Job
        return Job(title="", company=company, location="", url=url,
                   source="linkedin", source_key="linkedin_hr_posts",
                   description="", content_type="job_listing",
                   verified_by_signal=False)

    result = verify_signal(signal, search_fn=search_fn, job_builder=builder)
    assert result.is_verified_job
    assert result.verified_job.url == "https://www.linkedin.com/jobs/view/123"
    assert "v72_verified_signal" in result.verified_job.tags
    assert result.verified_job.verified_by_signal is True
    assert result.signal.verified is True


def test_verify_signal_no_url_emits_hiring_signal():
    from sources.hiring_signal_discovery import (
        detect_hiring_signal, verify_signal, _reset_v72_telemetry,
    )
    _reset_v72_telemetry()
    signal = detect_hiring_signal(
        "Our security team is hiring at CIB — SOC analysts wanted.")
    assert signal is not None
    result = verify_signal(signal, search_fn=lambda spec: [])
    assert result.decision == "hiring_signal"
    assert result.verified_job is None
    from sources.hiring_signal_discovery import get_v72_signal_telemetry
    t = get_v72_signal_telemetry()
    # The caller increments signals_detected; verify_signal only counts the
    # decision it made itself.
    assert t["signals_emitted_hiring_signal"] == 1
    assert t["signals_verified_job"] == 0


def test_verify_chain_order_and_one_failure_does_not_kill_it():
    from sources.hiring_signal_discovery import (
        HiringSignal, verify_signal, _reset_v72_telemetry,
    )
    _reset_v72_telemetry()
    order: list[str] = []

    def search_fn(spec):
        order.append(spec["kind"])
        if spec["kind"] == "careers_search":
            raise RuntimeError("backend down")
        if spec["kind"] == "linkedin_jobs":
            return [("https://careers.example/apply", "Security Engineer")]
        return []

    signal = HiringSignal(
        source_text="We're growing our security team at F5",
        company="F5", inferred_title="Security Engineer",
    )
    result = verify_signal(signal, search_fn=search_fn)
    # Without a job_builder, a found URL sets decision='verified_job' so the
    # caller knows a real application URL exists even when it builds the Job
    # itself.
    assert result.decision == "verified_job"
    assert result.signal.verified is True
    assert order == ["careers_search", "linkedin_jobs"]


# ── Main integration helpers ───────────────────────────────────────────────

def _make_hr_post(title, company, description, location=""):
    from models import Job
    return Job(title=title, company=company, location=location, url="",
               source="linkedin", source_key="linkedin_hr_posts",
               description=description, content_type="hr_post")


def test_mine_hiring_signals_filters_out_represented_roles():
    from main import _mine_hiring_signals

    post = _make_hr_post(
        "Hiring!", "Vodafone",
        "We're growing our security team at Vodafone! SOC analyst roles open.",
    )
    # Same company/role already in the pool as an hr_post — signal must NOT
    # duplicate it.
    duplicate = _make_hr_post(
        "SOC Analyst", "Vodafone",
        "SOC Analyst opening — apply here.",
    )
    signals = _mine_hiring_signals([post, duplicate])
    assert signals == []


def test_mine_hiring_signals_yields_only_real_signals():
    from main import _mine_hiring_signals

    real = _make_hr_post(
        "Signal", "QNB Egypt",
        "We're growing our security team at QNB Egypt in Cairo. Looking for "
        "incident response engineers.",
    )
    plain_job = _make_hr_post(
        "SOC Analyst II", "CIB",
        "SOC Analyst II — apply via LinkedIn jobs link.",
    )
    signals = _mine_hiring_signals([real, plain_job])
    assert len(signals) == 1
    assert signals[0].company.startswith("QNB")


# ── Signal dedup in the database ───────────────────────────────────────────

def test_signal_dedup_window_and_record():
    tmp = tempfile.mktemp(suffix=".db")
    try:
        from database import JobsDB
        db = JobsDB(tmp)
        key = "signal:vodafone:soc analyst"
        assert not db.was_signal_sent_recently(key, "egypt", hours=168)
        db.record_sent_signal(key, "egypt")
        assert db.was_signal_sent_recently(key, "egypt", hours=168)
        # Different channel stays independent.
        assert not db.was_signal_sent_recently(key, "remote", hours=168)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ── HIRING SIGNAL card formatting ──────────────────────────────────────────

def test_format_hiring_signal_message_no_apply_link():
    from telegram_sender import format_hiring_signal_message
    from sources.hiring_signal_discovery import HiringSignal

    signal = HiringSignal(
        source_text="We're growing our security team at Vodafone in Cairo",
        company="Vodafone", inferred_title="SOC Analyst",
        signal_source="linkedin_hr_post",
    )
    card = format_hiring_signal_message(signal)
    assert "HIRING SIGNAL" in card
    assert "Vodafone" in card
    assert "Apply Now" not in card
    assert "growing our security team" in card.lower()


# ── Opportunity Score factors ──────────────────────────────────────────────

def _score_of(job) -> int:
    from opportunity_score import compute_opportunity_score
    return compute_opportunity_score(job).total


def _job(title, company="", location="", verdict="CYBER_CONFIRMED",
         prob=0.9, description="", tags=None, **kw):
    from models import Job
    from datetime import datetime
    j = Job(title=title, company=company, url="https://example.com/1",
            source="linkedin", source_key="linkedin", location=location,
            description=description, tags=tags or [],
            content_type="job_listing", verified_by_signal=False,
            posted_date=datetime.now(), **kw)
    j.cyber_verdict = verdict
    j.cyber_probability = prob
    return j


def test_score_confirmed_egypt_job_is_top_tier():
    job = _job("SOC Analyst", company="NBE", location="Cairo, Egypt",
               description="SIEM monitoring, incident response, splunk",
               tags=["ml_prob:0.95"])
    score = _score_of(job)
    assert 80 <= score <= 100
    b = __import__("opportunity_score", fromlist=["compute_opportunity_score"]) \
        .compute_opportunity_score(job)
    assert b.factors["cyber"] >= 70  # CONFIRMED base with per-match depth bonus
    assert b.factors["location"] == 100  # Cairo physical
    assert b.factors["freshness"] >= 90


def test_score_non_cyber_candidate_scores_zero_cyber():
    job = _job("Financial Analyst", verdict="CYBER_NON_CYBER", prob=0.1,
               location="London, UK")
    b = __import__("opportunity_score", fromlist=["compute_opportunity_score"]) \
        .compute_opportunity_score(job)
    assert b.factors["cyber"] == 0  # NON_CYBER is always 0
    assert 0 <= b.factors["location"] <= 55  # UK is outside Egypt/Arab/remote


def test_score_is_bounded_and_degrades_with_age():
    from datetime import timedelta
    from opportunity_score import compute_opportunity_score

    fresh = _job("Security Engineer", company="Wiz",
                 location="Cairo, Egypt",
                 description="kubernetes aws edr siem docker",
                 tags=["ml_prob:0.9"])
    old = _job("Security Engineer", company="Wiz",
               location="Cairo, Egypt",
               description="kubernetes aws edr siem docker",
               tags=["ml_prob:0.9"])
    old.posted_date = __import__("datetime", fromlist=["datetime"]).datetime.now() - timedelta(days=30)
    assert compute_opportunity_score(fresh).total > compute_opportunity_score(old).total
    assert 0 <= compute_opportunity_score(fresh).total <= 100
    assert 0 <= compute_opportunity_score(old).total <= 100


def test_score_signal_verified_job_gains_velocity_bonus():
    job = _job("Red Team Engineer", company="Tenable", location="Remote",
               tags=["v72_verified_signal", "ml_prob:0.9"])
    b = __import__("opportunity_score", fromlist=["compute_opportunity_score"]) \
        .compute_opportunity_score(job)
    assert b.factors["velocity"] == 96


def test_opportunity_block_format_matches_requested_card():
    from opportunity_score import compute_opportunity_score, format_opportunity_block

    job = _job("SOC Analyst", company="CIB", location="Cairo, Egypt",
               description="incident response siem splunk", tags=[])
    block = format_opportunity_block(compute_opportunity_score(job))
    assert "OPPORTUNITY SCORE:" in block
    assert "Why prioritized:" in block
    assert "Cyber relevance:" in block
    assert "Freshness:" in block
    assert "Location fit:" in block
    assert "Employer signal:" in block
    assert "Competition:" in block
    assert "Skill match:" in block
    assert "✓" in block


def test_job_card_includes_opportunity_block():
    from telegram_sender import format_job_message

    job = _job("Security Engineer", company="F5", location="Cairo, Egypt",
               description="firewall vpn waf security architecture",
               tags=["ml_prob:0.92"])
    card = format_job_message(job)
    assert "OPPORTUNITY SCORE:" in card
    assert "Why prioritized:" in card
