"""
sources/linkedin_extended.py — v46
Additional LinkedIn search queries focused on Egypt and Gulf cybersecurity roles.

Architecture:
  • Wraps linkedin_unified.py's internal search function with more query sets.
  • Runs AFTER linkedin_unified to avoid duplicating the same searches.
  • geo_hint injected for downstream geo classifier.

Env vars:
  LINKEDIN_EXTENDED_ENABLED   Enable/disable (default: true)
  LINKEDIN_EXTENDED_MAX_JOBS  Max per search query (default: 10)
"""

from __future__ import annotations

import logging
import os
import time
from typing import NamedTuple

from models import Job

log = logging.getLogger(__name__)

_ENABLED = os.getenv("LINKEDIN_EXTENDED_ENABLED", "true").lower() in ("1", "true", "yes")
_MAX_PER_QUERY = int(os.getenv("LINKEDIN_EXTENDED_MAX_JOBS", "10"))

SOURCE_NAME = "linkedin_extended"


class _QuerySpec(NamedTuple):
    keywords: str
    location: str
    geo_hint: str
    job_type: str = ""       # "full_time" | "internship" | ""
    experience: str = ""     # "1" entry | "2" associate | "3" mid | "4" senior


_QUERIES: list[_QuerySpec] = [
    # ── Egypt — Targeted ─────────────────────────────────────────────
    _QuerySpec("cybersecurity analyst",         "Egypt",          "egypt"),
    _QuerySpec("SOC analyst",                   "Cairo",          "egypt"),
    _QuerySpec("penetration tester",            "Egypt",          "egypt"),
    _QuerySpec("information security",          "Cairo, Egypt",   "egypt"),
    _QuerySpec("GRC analyst",                   "Egypt",          "egypt"),
    _QuerySpec("cloud security engineer",       "Egypt",          "egypt"),
    _QuerySpec("network security engineer",     "Egypt",          "egypt"),
    _QuerySpec("application security",          "Egypt",          "egypt"),
    _QuerySpec("security engineer",             "Cairo",          "egypt"),
    _QuerySpec("CISO",                          "Egypt",          "egypt"),
    _QuerySpec("cybersecurity intern",          "Egypt",          "egypt", "internship", "1"),
    _QuerySpec("security operations",           "Egypt",          "egypt"),
    _QuerySpec("devsecops",                     "Egypt",          "egypt"),
    _QuerySpec("vulnerability management",      "Egypt",          "egypt"),
    _QuerySpec("threat intelligence analyst",   "Egypt",          "egypt"),
    # Arabic queries
    _QuerySpec("أمن معلومات",                  "مصر",            "egypt"),
    _QuerySpec("أمن سيبراني",                  "القاهرة",        "egypt"),
    # ── Saudi Arabia ─────────────────────────────────────────────────
    _QuerySpec("cybersecurity analyst",         "Saudi Arabia",   "gulf"),
    _QuerySpec("SOC analyst",                   "Riyadh",         "gulf"),
    _QuerySpec("penetration tester",            "Saudi Arabia",   "gulf"),
    _QuerySpec("information security manager",  "Saudi Arabia",   "gulf"),
    _QuerySpec("GRC consultant",                "Saudi Arabia",   "gulf"),
    _QuerySpec("cloud security",                "Riyadh",         "gulf"),
    _QuerySpec("CISO",                          "Saudi Arabia",   "gulf"),
    _QuerySpec("security operations center",    "Saudi Arabia",   "gulf"),
    _QuerySpec("cybersecurity",                 "Jeddah",         "gulf"),
    _QuerySpec("network security",              "Saudi Arabia",   "gulf"),
    # NEOM + Vision 2030 companies
    _QuerySpec("cybersecurity NEOM",            "Saudi Arabia",   "gulf"),
    _QuerySpec("information security Aramco",   "Saudi Arabia",   "gulf"),
    # ── UAE + Other Gulf ─────────────────────────────────────────────
    _QuerySpec("cybersecurity analyst",         "Dubai",          "gulf"),
    _QuerySpec("SOC analyst",                   "Dubai",          "gulf"),
    _QuerySpec("security engineer",             "Abu Dhabi",      "gulf"),
    _QuerySpec("cloud security",                "UAE",            "gulf"),
    _QuerySpec("cybersecurity",                 "Qatar",          "gulf"),
    _QuerySpec("information security",          "Kuwait",         "gulf"),
    # ── Remote — Entry Level Focus ───────────────────────────────────
    _QuerySpec("cybersecurity intern remote",    "",              "remote", "internship", "1"),
    _QuerySpec("junior security analyst remote", "",             "remote", "full_time",  "1"),
    _QuerySpec("SOC analyst remote",             "",             "remote", "full_time",  "2"),
    _QuerySpec("GRC analyst remote",             "",             "remote"),
    _QuerySpec("devsecops remote",               "",             "remote"),
]


def fetch_linkedin_extended() -> list[Job]:
    """Run extended LinkedIn searches focused on Egypt, Gulf, and remote entry-level."""
    if not _ENABLED:
        log.info("linkedin_extended: disabled")
        return []

    # Import linkedin_unified internals carefully
    try:
        from sources.linkedin_unified import _linkedin_search_jobs
    except ImportError:
        log.warning("linkedin_extended: cannot import _linkedin_search_jobs — skipping")
        return []

    all_jobs: list[Job] = []
    seen_urls: set[str] = set()

    for spec in _QUERIES:
        try:
            batch = _linkedin_search_jobs(
                keywords=spec.keywords,
                location=spec.location,
                max_results=_MAX_PER_QUERY,
                job_type=spec.job_type,
                experience_level=spec.experience,
            )
            fresh = []
            for job in batch:
                if job.url not in seen_urls:
                    seen_urls.add(job.url)
                    job.source = SOURCE_NAME
                    job.geo_hint = spec.geo_hint
                    fresh.append(job)
            all_jobs.extend(fresh)
            if fresh:
                log.debug("LinkedIn Extended [%s / %s]: %d", spec.keywords, spec.location, len(fresh))
            time.sleep(0.8)   # polite between queries
        except Exception as exc:
            log.debug("linkedin_extended: '%s' failed: %s", spec.keywords, exc)

    log.info("LinkedIn Extended total: %d raw jobs", len(all_jobs))
    return all_jobs
