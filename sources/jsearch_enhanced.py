"""
sources/jsearch_enhanced.py
============================
JSearch (RapidAPI) enhanced connector — aggregates LinkedIn + Indeed + Glassdoor.

Merges Bot0 linkedin_api.py Egypt/Gulf-focused queries with Bot1's
existing remote/global searches into one unified connector.

Architecture rules:
  • No embedded is_sec() filter — Bot1's intelligence pipeline classifies.
  • LinkedIn URL preferred over other apply URLs (preserves diversity tracking).
  • posted_date preserved from API timestamps for freshness scoring.
  • Canonical URL via linkedin_url_utils.canonicalize_job_url.

Environment variables:
    RAPIDAPI_KEY         Required. Skip gracefully if absent.
    JSEARCH_PAGES_LOCAL  Pages per local (Egypt/Gulf) query. Default: 1.
    JSEARCH_PAGES_REMOTE Pages per remote query.               Default: 1.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import NamedTuple

import config
from models import Job
from sources.http_utils import get_json
from linkedin_url_utils import canonicalize_job_url

log = logging.getLogger(__name__)

SOURCE_NAME = "jsearch_enhanced"
JSEARCH_HOST = "jsearch.p.rapidapi.com"

_PAGES_LOCAL  = int(getattr(config, "JSEARCH_PAGES_LOCAL", 1))
_PAGES_REMOTE = int(getattr(config, "JSEARCH_PAGES_REMOTE", 1))


class _SearchSpec(NamedTuple):
    query: str
    remote_only: bool
    geo_hint: str      # "egypt" | "gulf" | "remote" | ""


# ---------------------------------------------------------------------------
# Search matrix
# ---------------------------------------------------------------------------

_SEARCHES: list[_SearchSpec] = [
    # ----- Egypt (Local) -----
    _SearchSpec("cybersecurity Egypt",               False, "egypt"),
    _SearchSpec("SOC analyst Egypt",                 False, "egypt"),
    _SearchSpec("penetration tester Egypt",          False, "egypt"),
    _SearchSpec("security engineer Cairo Egypt",     False, "egypt"),
    _SearchSpec("information security Egypt",        False, "egypt"),
    _SearchSpec("GRC analyst Egypt",                 False, "egypt"),
    _SearchSpec("IAM analyst Egypt",                 False, "egypt"),
    _SearchSpec("application security Egypt",        False, "egypt"),
    _SearchSpec("DevSecOps engineer Egypt",          False, "egypt"),
    _SearchSpec("threat intelligence Egypt",         False, "egypt"),
    _SearchSpec("red team Egypt",                    False, "egypt"),
    _SearchSpec("cloud security Egypt",              False, "egypt"),
    _SearchSpec("security intern Egypt",             False, "egypt"),
    _SearchSpec("junior cybersecurity Egypt",        False, "egypt"),
    # ----- Gulf – Saudi Arabia -----
    _SearchSpec("cybersecurity Saudi Arabia",        False, "gulf"),
    _SearchSpec("SOC analyst Riyadh Saudi Arabia",   False, "gulf"),
    _SearchSpec("penetration tester Saudi Arabia",   False, "gulf"),
    _SearchSpec("security engineer Jeddah",          False, "gulf"),
    _SearchSpec("information security Saudi Arabia", False, "gulf"),
    _SearchSpec("GRC analyst Saudi Arabia",          False, "gulf"),
    _SearchSpec("IAM engineer Saudi Arabia",         False, "gulf"),
    _SearchSpec("application security Dubai UAE",    False, "gulf"),
    _SearchSpec("DevSecOps engineer Saudi Arabia",   False, "gulf"),
    _SearchSpec("threat intelligence Dubai UAE",     False, "gulf"),
    _SearchSpec("red team Saudi Arabia",             False, "gulf"),
    _SearchSpec("cloud security Saudi Arabia",       False, "gulf"),
    _SearchSpec("CISO Saudi Arabia",                 False, "gulf"),
    _SearchSpec("network security Saudi Arabia",     False, "gulf"),
    # ----- Gulf – UAE / Other -----
    _SearchSpec("cybersecurity Dubai UAE",           False, "gulf"),
    _SearchSpec("SOC analyst Dubai",                 False, "gulf"),
    _SearchSpec("security engineer UAE",             False, "gulf"),
    _SearchSpec("information security Qatar",        False, "gulf"),
    _SearchSpec("cybersecurity Kuwait",              False, "gulf"),
    # ----- Remote worldwide -----
    _SearchSpec("cybersecurity engineer remote",         True, "remote"),
    _SearchSpec("information security engineer remote",  True, "remote"),
    _SearchSpec("security analyst remote",               True, "remote"),
    _SearchSpec("penetration tester remote",             True, "remote"),
    _SearchSpec("SOC analyst remote",                    True, "remote"),
    _SearchSpec("threat intelligence analyst remote",    True, "remote"),
    _SearchSpec("application security engineer remote",  True, "remote"),
    _SearchSpec("cloud security engineer remote",        True, "remote"),
    _SearchSpec("devsecops engineer remote",             True, "remote"),
    _SearchSpec("GRC analyst remote",                    True, "remote"),
    _SearchSpec("IAM engineer remote",                   True, "remote"),
    _SearchSpec("security architect remote",             True, "remote"),
    _SearchSpec("detection engineer remote",             True, "remote"),
    _SearchSpec("red team operator remote",              True, "remote"),
    _SearchSpec("security intern remote",                True, "remote"),
]

_PUBLISHER_MAP: dict[str, str] = {
    "linkedin.com": "LinkedIn",
    "indeed.com": "Indeed",
    "glassdoor.com": "Glassdoor",
    "ziprecruiter.com": "ZipRecruiter",
    "monster.com": "Monster",
}


# ---------------------------------------------------------------------------
# Low-level fetcher
# ---------------------------------------------------------------------------

def _jsearch_page(query: str, page: int, remote_only: bool) -> list[dict]:
    """Fetch one page from the JSearch API."""
    api_key = getattr(config, "RAPIDAPI_KEY", "")
    if not api_key:
        return []

    params: dict[str, str] = {
        "query":       query,
        "page":        str(page),
        "num_pages":   "1",
        "date_posted": "today",
    }
    if remote_only:
        params["remote_jobs_only"] = "true"

    data = get_json(
        f"https://{JSEARCH_HOST}/search",
        params=params,
        headers={
            "X-RapidAPI-Key":  api_key,
            "X-RapidAPI-Host": JSEARCH_HOST,
        },
    )
    if not data or "data" not in data:
        return []
    return data["data"]


def _preferred_url(item: dict) -> str:
    """Prefer LinkedIn URL from apply_options, fall back to job_apply_link."""
    for option in item.get("apply_options", []):
        link = option.get("apply_link", "")
        if "linkedin.com" in link:
            return link
    return item.get("job_apply_link", "") or item.get("job_google_link", "")


def _detect_publisher(url: str, item: dict | None = None) -> str:
    api_publisher = str((item or {}).get("job_publisher") or "").strip().lower()
    if api_publisher:
        for name in _PUBLISHER_MAP.values():
            if api_publisher == name.lower():
                return name
    for domain, name in _PUBLISHER_MAP.items():
        if domain in url:
            return name
    return "JSearch"


def _parse_salary(item: dict) -> str:
    min_sal = item.get("job_min_salary")
    max_sal = item.get("job_max_salary")
    currency = item.get("job_salary_currency", "")
    period   = item.get("job_salary_period", "")
    if min_sal and max_sal:
        return f"{min_sal:,.0f}–{max_sal:,.0f} {currency} / {period}"
    if min_sal:
        return f"{min_sal:,.0f}+ {currency} / {period}"
    return ""


def _parse_location(item: dict) -> str:
    city    = item.get("job_city", "") or ""
    state   = item.get("job_state", "") or ""
    country = item.get("job_country", "") or ""
    if city and state:
        return f"{city}, {state}"
    if city:
        return f"{city}, {country}" if country else city
    return country or "Not specified"


def _items_to_jobs(items: list[dict], geo_hint: str) -> list[Job]:
    jobs: list[Job] = []
    seen_ids: set[str] = set()

    for item in items:
        job_id = item.get("job_id", "") or item.get("job_apply_link", "")
        if not job_id or job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        title   = (item.get("job_title") or "").strip()
        company = (item.get("employer_name") or "").strip()
        url     = _preferred_url(item)

        if not title or not url:
            continue

        url = canonicalize_job_url(url)
        location = _parse_location(item)

        posted_at: datetime | None = None
        ts = item.get("job_posted_at_timestamp")
        if ts:
            try:
                posted_at = datetime.fromtimestamp(int(ts))
            except Exception:
                pass

        publisher = _detect_publisher(url, item)
        source_key = "linkedin_jsearch" if publisher == "LinkedIn" else SOURCE_NAME

        jobs.append(Job(
            title=title,
            company=company,
            location=location,
            url=url,
            source=SOURCE_NAME,
            source_key=source_key,
            description=(item.get("job_description") or "")[:500],
            is_remote=bool(item.get("job_is_remote", False)),
            job_type=item.get("job_employment_type", ""),
            salary=_parse_salary(item),
            posted_date=posted_at,
            geo_hint=geo_hint,
            original_source=f"JSearch ({publisher})",
            tags=["jsearch", f"publisher:{publisher.lower()}"],
        ))

    return jobs


# ---------------------------------------------------------------------------
# Public connector
# ---------------------------------------------------------------------------

def fetch_jsearch_enhanced() -> list[Job]:
    """Fetch cybersecurity jobs via JSearch across Egypt, Gulf, and remote searches.

    Returns raw Job objects for Bot1's intelligence pipeline.
    The caller is responsible for:
        • Cyber classification
        • Geo classification (geo_hint is a hint only, not authoritative)
        • Scoring and deduplication
    """
    api_key = getattr(config, "RAPIDAPI_KEY", "")
    if not api_key:
        log.info("jsearch_enhanced: RAPIDAPI_KEY not set — skipping.")
        return []

    all_jobs: list[Job] = []
    seen_ids: set[str] = set()

    for spec in _SEARCHES:
        num_pages = _PAGES_REMOTE if spec.remote_only else _PAGES_LOCAL
        for page in range(1, num_pages + 1):
            try:
                items = _jsearch_page(spec.query, page, spec.remote_only)
                batch = _items_to_jobs(items, spec.geo_hint)
                # Cross-query dedup by URL
                fresh = [j for j in batch if j.url not in seen_ids]
                seen_ids.update(j.url for j in fresh)
                all_jobs.extend(fresh)
                if fresh:
                    log.debug(
                        "JSearch [%s] p%d: %d jobs",
                        spec.query[:40], page, len(fresh),
                    )
            except Exception as exc:
                log.warning(
                    "jsearch_enhanced: '%s' p%d failed: %s",
                    spec.query, page, exc,
                )
            time.sleep(0.5)   # RapidAPI rate-limit courtesy delay

    log.info("JSearch Enhanced total: %d raw jobs", len(all_jobs))
    return all_jobs
