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


# ── v84: always-on internships lanes (all specialties, esp. internships) ────

def test_internships_lanes_cover_all_specialties():
    from sources.linkedin_unified import _build_internships_lanes, _build_query_plan
    lanes = _build_internships_lanes()
    assert len(lanes) == 10
    text = " ".join(l.keywords for l in lanes)
    for kw in ("Cybersecurity Intern", "SOC Analyst Intern",
               "Penetration Testing Intern", "GRC Trainee",
               "Network Security Intern", "Graduate Program"):
        assert kw in text
    for slot in range(3):
        plan = _build_query_plan(slot)
        assert sum(1 for q in plan if q.lane_type == "internships") == 10


# ── v83: employer-lane scale (distinct sets, not 3x keywords) ───────────────

def test_company_chunk_and_plan_scale():
    from sources.linkedin_unified import _build_company_lanes, _build_query_plan
    lanes = _build_company_lanes(0)
    assert len(lanes) == 14
    plan = _build_query_plan(0)
    assert len(plan) <= config.LINKEDIN_MAX_QUERIES_PER_RUN
    assert len(plan) >= 100
    company = sum(1 for q in plan if q.lane_type == "company")
    assert company >= 40  # employer lanes dominate the plan


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


# ── v80: 429 hardening + honest dateless + mirror skip ───────────────────────

def test_sleep_flood_window_respects_budget_and_cap(monkeypatch):
    import telegram_sender as ts
    calls = []
    monkeypatch.setattr(ts.time, "sleep", lambda s: calls.append(s))
    monkeypatch.setattr(ts, "_telegram_budget_remaining", lambda: 10.0)
    ts._sleep_flood_window(37)
    assert calls == [10.0]  # capped by budget, not 39
    calls.clear()
    monkeypatch.setattr(ts, "_telegram_budget_remaining", lambda: 600.0)
    ts._sleep_flood_window(37)
    assert calls == [39.0]
    calls.clear()
    ts._sleep_flood_window(None)
    assert calls == [2.0]  # floor courtesy pause on bare 429s


def test_dateless_marketplace_job_does_not_crash_digest():
    from sources.marketplace_sources import _to_jobs, MarketplaceSpec
    spec = MarketplaceSpec("guru", "Guru", ("https://example.com/",),
                           "client_project", "remote", 20)
    rows = [("SOC Analyst", "https://example.com/j/1", "SOC SIEM role", None)]
    jobs = _to_jobs(rows, spec, "jina")
    assert len(jobs) == 1
    assert jobs[0].posted_date is None
    assert jobs[0].provenance_hash


def test_marketplace_skips_linkedin_mirror_urls(monkeypatch):
    import sources.marketplace_sources as ms
    seen = []

    class R:
        text = ""
        error_code = "empty"
    monkeypatch.setattr(
        ms, "get_text_result",
        lambda url, **kw: (seen.append(url), R())[1],
    )
    monkeypatch.setattr(ms, "_fetch_via_jina", lambda url: None)
    ms.fetch_marketplace("wuzzuf")
    assert seen
    assert all("linkedin.com" not in u.lower() for u in seen)


# ── v80: Egyptian-Arab package ─────────────────────────────────────────────

def test_egypt_boards_specs_registered_and_egytech_gone():
    from sources.source_registry import get_source_specs
    keys = {s.key for s in get_source_specs()}
    assert {"wuzzuf_rss", "bayt_egypt", "drjobpro"} <= keys
    assert "egytech_fyi" not in keys


def test_wazzif_reader_rescue_path(monkeypatch):
    import sources.egypt_boards as boards
    html = ('<a href="/jobs/soc-1">SOC Analyst</a> context SIEM incident '
            'response posted 3 hours ago ' + 'x' * 600)

    class Resp:
        status_code = 403
        text = ""
    monkeypatch.setattr(boards.requests, "get", lambda *_a, **_k: Resp())
    import sources.http_utils as hu
    monkeypatch.setattr(hu, "get_text", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("net")))
    result = boards.fetch_wazzif()
    assert result.status == "blocked"
    assert result.error_code in ("wazzif_unavailable", "wazzif_blocked")


def test_greenhouse_v80_slugs_present():
    from sources.greenhouse_expanded import _GREENHOUSE_CYBERSEC
    slugs = {e.slug for e in _GREENHOUSE_CYBERSEC}
    # v84: confirmed-404 slugs removed, working ones kept.
    assert {"expel", "blumira"} <= slugs
    assert not {"snyk", "redcanary", "drata", "cobalt"} & slugs


# ── v82: TLS-fingerprint rescue + employer coverage ─────────────────────────

def test_cffi_helper_returns_none_without_lib(monkeypatch):
    import sys
    import sources.http_utils as hu
    monkeypatch.setitem(sys.modules, "curl_cffi", None)
    # Force the lazy import to fail even if the wheel exists on this box.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "curl_cffi" or name.startswith("curl_cffi."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(hu, "_CFFI_MISSING_LOGGED", True)
    assert hu.get_text_cffi("https://example.com/") is None


def test_cffi_helper_parses_200_body(monkeypatch):
    import sys
    import sources.http_utils as hu

    class Resp:
        status_code = 200
        text = "<html>jobs</html>"

    class FakeRequests:
        @staticmethod
        def get(url, **kwargs):
            assert kwargs.get("impersonate") == "chrome120"
            return Resp()

    monkeypatch.setitem(sys.modules, "curl_cffi", type(sys)("curl_cffi"))
    sys.modules["curl_cffi"].requests = FakeRequests
    assert hu.get_text_cffi("https://example.com/") == "<html>jobs</html>"


def test_paymob_fawry_in_employer_registry():
    from sources.egypt_employer_registry import EGYPT_EMPLOYERS, linkedin_employer_queries
    keys = {e.key for e in EGYPT_EMPLOYERS}
    assert {"paymob", "fawry"} <= keys
    queries = linkedin_employer_queries()
    assert len(queries) == len(EGYPT_EMPLOYERS)
    assert any("Paymob" in q for q, _, _ in queries)


def test_arab_company_lanes_cover_regional_cyber_arms():
    from sources.linkedin_unified import _build_company_lanes
    text = " ".join(
        l.keywords for slot in range(6) for l in _build_company_lanes(slot)
    )
    for name in ("Sirar", "Help AG", "Tamara", "Zain", "Trend Micro"):
        assert name in text


# ── v87: funnel counts unique jobs, Egypt guard fits its ceiling ─────────────

def test_funnel_routed_sent_use_unique_job_units():
    import re
    import pathlib
    src = pathlib.Path(ROOT, "main.py").read_text(encoding="utf-8")
    assert "_v75_by_geo[_g].add(" in src  # pair→unique fix present


def test_egypt_direct_guard_fits_spec_ceiling():
    import config
    import sources.egypt_direct as ed
    assert ed._FETCH_BUDGET_SECONDS < config.CAREERS_API_SOURCE_TIMEOUT_SECONDS


# ── v87: JSearch error visibility + Bayt fallback removal ────────────────────

def test_jsearch_logs_first_transport_error(monkeypatch):
    import config as cfg
    import sources.jsearch_enhanced as je
    from sources.http_utils import HttpTextResult
    monkeypatch.setattr(cfg, "RAPIDAPI_KEY", "dummy", raising=False)
    monkeypatch.setattr(je, "_JSEARCH_FIRST_ERROR_LOGGED", False)
    # NOTE: _jsearch_page imports get_text_result lazily from http_utils,
    # so the patch target is http_utils, not jsearch_enhanced.
    monkeypatch.setattr(
        "sources.http_utils.get_text_result",
        lambda *a, **k: HttpTextResult(None, 403, "http_403"),
    )
    assert je._jsearch_page("soc egypt", 1, False) == []
    assert je._JSEARCH_FIRST_ERROR_LOGGED is True


def test_bayt_egypt_has_no_legacy_reader_fallback():
    import pathlib
    src = pathlib.Path(ROOT, "sources", "egypt_direct.py").read_text(encoding="utf-8")
    # the per-query reader rescue stays; the 20s legacy _parse_board pass is gone
    assert "from sources.jina_scraper import" not in src
    assert "_parse_board" not in src


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
