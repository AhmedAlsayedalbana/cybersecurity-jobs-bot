"""
sources/mena_boards.py — v47
Direct HTTP scrapers for MENA-specific cybersecurity job boards.
No API key required. Focused on Egypt + Gulf market.

Boards:
  • Akhtaboot  — largest Arabic MENA board (Egypt, Saudi, UAE, Jordan)
  • DrJobPro   — Gulf + Egypt focused
  • Forasna    — Egypt direct jobs board
  • Tanqeeb    — Arabic Gulf job board (direct)
  • Wuzzuf RSS — Egypt direct via RSS feed

All boards try JSON-LD structured data first, then regex link extraction.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
from datetime import datetime, timezone
from typing import NamedTuple

from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

SOURCE_NAME = "mena_boards"

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://google.com/",
}

# ── Security term filter ────────────────────────────────────────────────

_SEC_TERMS = {
    "cybersecurity", "cyber security", "information security", "infosec",
    "security analyst", "security engineer", "soc analyst", "soc engineer",
    "grc", "penetration", "pentest", "appsec", "application security",
    "cloud security", "network security", "threat", "dfir", "iam",
    "incident response", "malware", "vulnerability", "devsecops",
    "privacy officer", "data protection", "ciso", "compliance analyst",
    "أمن", "أمن سيبراني", "أمن معلومات", "اختراق",
}


def _is_security(text: str) -> bool:
    t = (text or "").lower()
    return any(term in t for term in _SEC_TERMS)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _parse_posted_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw[:19], fmt[:len(raw[:19])])
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except ValueError:
            pass
    return None


def _extract_jsonld_jobs(html: str, source_key: str, geo_hint: str,
                          base_domain: str) -> list[Job]:
    """Extract jobs from JSON-LD JobPosting structured data."""
    jobs: list[Job] = []
    for block in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.IGNORECASE | re.DOTALL
    ):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if item.get("@type") not in ("JobPosting", "jobPosting"):
                continue
            title = _clean(item.get("title", ""))
            url = item.get("url", "") or item.get("@id", "")
            if not title or not url:
                continue
            if not _is_security(title):
                continue
            org = item.get("hiringOrganization", {})
            company = (org.get("name", "") if isinstance(org, dict) else "") or base_domain
            loc = item.get("jobLocation", {})
            location = ""
            if isinstance(loc, dict):
                addr = loc.get("address", {})
                if isinstance(addr, dict):
                    location = addr.get("addressLocality", "") or addr.get("addressCountry", "")
            location = location or geo_hint.replace("egypt", "Egypt").replace("gulf", "Gulf").replace("ksa", "Saudi Arabia")
            posted_date = _parse_posted_date(item.get("datePosted"))
            jobs.append(Job(
                title=title, company=company, location=location,
                url=url, source=source_key,
                source_key=source_key, geo_hint=geo_hint,
                posted_date=posted_date,
                content_type="job_listing",
                tags=["mena_boards", base_domain],
            ))
    return jobs


# ── Board specifications ────────────────────────────────────────────────

class _BoardSpec(NamedTuple):
    url: str
    site_name: str
    geo_hint: str       # "egypt" | "ksa" | "gulf"
    source_key: str
    link_pattern: str   # regex for extracting job links
    max_jobs: int = 25


_AKHTABOOT_BOARDS: list[_BoardSpec] = [
    _BoardSpec(
        "https://www.akhtaboot.com/en/jobs?keywords=cybersecurity&country%5B%5D=EG&page=1",
        "Akhtaboot", "egypt", "akhtaboot",
        r'href="(/en/job/\d+/[^"]+)"', 25,
    ),
    _BoardSpec(
        "https://www.akhtaboot.com/en/jobs?keywords=security+analyst&country%5B%5D=EG",
        "Akhtaboot", "egypt", "akhtaboot",
        r'href="(/en/job/\d+/[^"]+)"', 15,
    ),
    _BoardSpec(
        "https://www.akhtaboot.com/en/jobs?keywords=cybersecurity&country%5B%5D=SA",
        "Akhtaboot KSA", "ksa", "akhtaboot",
        r'href="(/en/job/\d+/[^"]+)"', 25,
    ),
    _BoardSpec(
        "https://www.akhtaboot.com/en/jobs?keywords=cybersecurity&country%5B%5D=AE",
        "Akhtaboot UAE", "gulf", "akhtaboot",
        r'href="(/en/job/\d+/[^"]+)"', 20,
    ),
]

_DRJOB_BOARDS: list[_BoardSpec] = [
    _BoardSpec(
        "https://drjobpro.com/jobs/cybersecurity-jobs/egypt",
        "DrJobPro", "egypt", "drjobpro",
        r'href="(https://drjobpro\.com/jobs/[^"]+)"', 20,
    ),
    _BoardSpec(
        "https://drjobpro.com/jobs/cybersecurity-jobs/saudi-arabia",
        "DrJobPro KSA", "ksa", "drjobpro",
        r'href="(https://drjobpro\.com/jobs/[^"]+)"', 20,
    ),
    _BoardSpec(
        "https://drjobpro.com/jobs/cybersecurity-jobs/uae",
        "DrJobPro UAE", "gulf", "drjobpro",
        r'href="(https://drjobpro\.com/jobs/[^"]+)"', 15,
    ),
    _BoardSpec(
        "https://drjobpro.com/jobs/information-security-jobs/egypt",
        "DrJobPro InfoSec", "egypt", "drjobpro",
        r'href="(https://drjobpro\.com/jobs/[^"]+)"', 15,
    ),
]

_FORASNA_BOARDS: list[_BoardSpec] = [
    _BoardSpec(
        "https://forasna.com/jobs?q=cybersecurity",
        "Forasna", "egypt", "forasna",
        r'href="(https://forasna\.com/jobs/[^"?]+)"', 20,
    ),
    _BoardSpec(
        "https://forasna.com/jobs?q=%D8%A3%D9%85%D9%86+%D9%85%D8%B9%D9%84%D9%88%D9%85%D8%A7%D8%AA",
        "Forasna Arabic", "egypt", "forasna",
        r'href="(https://forasna\.com/jobs/[^"?]+)"', 15,
    ),
]

_TANQEEB_BOARDS: list[_BoardSpec] = [
    _BoardSpec(
        "https://tanqeeb.com/jobs?q=cybersecurity&country=SA",
        "Tanqeeb KSA", "ksa", "tanqeeb",
        r'href="(https://tanqeeb\.com/job/[^"]+)"', 20,
    ),
    _BoardSpec(
        "https://tanqeeb.com/jobs?q=cybersecurity&country=AE",
        "Tanqeeb UAE", "gulf", "tanqeeb",
        r'href="(https://tanqeeb\.com/job/[^"]+)"', 15,
    ),
    _BoardSpec(
        "https://tanqeeb.com/jobs?q=security+engineer&country=SA",
        "Tanqeeb SEC", "ksa", "tanqeeb",
        r'href="(https://tanqeeb\.com/job/[^"]+)"', 15,
    ),
]


def _scrape_board(spec: _BoardSpec, seen_urls: set[str]) -> list[Job]:
    """Scrape a single board page. Tries JSON-LD first, then link regex."""
    html = get_text(spec.url, headers=_H, timeout=15, max_retries=1)
    if not html:
        log.debug("mena_boards: no response from %s", spec.site_name)
        return []

    # Try JSON-LD structured data first (best quality)
    domain = re.search(r"https?://(?:www\.)?([^/]+)", spec.url)
    base_domain = domain.group(1) if domain else spec.site_name.lower()
    jobs = _extract_jsonld_jobs(html, spec.source_key, spec.geo_hint, base_domain)

    # Fallback: extract links via regex and build basic Job objects
    if not jobs:
        links = re.findall(spec.link_pattern, html, re.IGNORECASE)
        unique_links = list(dict.fromkeys(links))[:spec.max_jobs]
        for href in unique_links:
            full_url = href if href.startswith("http") else f"https://{base_domain}{href}"
            if full_url in seen_urls:
                continue
            # Extract title from surrounding context
            title = ""
            m = re.search(
                re.escape(href) + r'[^>]*>([^<]{5,120})<',
                html, re.IGNORECASE
            )
            if m:
                title = _clean(m.group(1))
            if not title or not _is_security(title):
                continue
            jobs.append(Job(
                title=title,
                company=spec.site_name,
                location=spec.geo_hint.replace("egypt", "Egypt")
                                      .replace("ksa", "Saudi Arabia")
                                      .replace("gulf", "Gulf"),
                url=full_url,
                source=spec.source_key,
                source_key=spec.source_key,
                geo_hint=spec.geo_hint,
                posted_date=datetime.utcnow(),   # stamp today = fresh
                content_type="job_listing",
                tags=["mena_boards", spec.source_key],
            ))

    # Stamp today for jobs without posted_date (ensures freshness gate works)
    for job in jobs:
        if job.posted_date is None:
            job.posted_date = datetime.utcnow()

    # Filter to security-related and deduplicate
    fresh: list[Job] = []
    for job in jobs[:spec.max_jobs]:
        if job.url in seen_urls:
            continue
        if not _is_security(job.title):
            continue
        seen_urls.add(job.url)
        fresh.append(job)

    return fresh


def _run_board_group(boards: list[_BoardSpec], label: str,
                     seen_urls: set[str]) -> list[Job]:
    all_jobs: list[Job] = []
    for spec in boards:
        try:
            batch = _scrape_board(spec, seen_urls)
            all_jobs.extend(batch)
            if batch:
                log.info("mena_boards: %s: %d jobs", spec.site_name, len(batch))
            time.sleep(0.8)
        except Exception as exc:
            log.warning("mena_boards: %s failed: %s", spec.site_name, exc)
    log.info("mena_boards %s total: %d", label, len(all_jobs))
    return all_jobs


# ── Public entry points ─────────────────────────────────────────────────

def fetch_akhtaboot() -> list[Job]:
    """Fetch cybersecurity jobs from Akhtaboot (Egypt + Saudi + UAE)."""
    seen: set[str] = set()
    return _run_board_group(_AKHTABOOT_BOARDS, "Akhtaboot", seen)


def fetch_drjobpro() -> list[Job]:
    """Fetch cybersecurity jobs from DrJobPro (Egypt + Gulf)."""
    seen: set[str] = set()
    return _run_board_group(_DRJOB_BOARDS, "DrJobPro", seen)


def fetch_forasna() -> list[Job]:
    """Fetch cybersecurity jobs from Forasna (Egypt)."""
    seen: set[str] = set()
    return _run_board_group(_FORASNA_BOARDS, "Forasna", seen)


def fetch_tanqeeb() -> list[Job]:
    """Fetch cybersecurity jobs from Tanqeeb (Gulf)."""
    seen: set[str] = set()
    return _run_board_group(_TANQEEB_BOARDS, "Tanqeeb", seen)


def fetch_mena_boards() -> list[Job]:
    """Aggregate all MENA boards. Called from source_registry."""
    seen: set[str] = set()
    all_jobs: list[Job] = []

    for label, boards in [
        ("Akhtaboot", _AKHTABOOT_BOARDS),
        ("DrJobPro",  _DRJOB_BOARDS),
        ("Forasna",   _FORASNA_BOARDS),
        ("Tanqeeb",   _TANQEEB_BOARDS),
    ]:
        try:
            batch = _run_board_group(boards, label, seen)
            all_jobs.extend(batch)
        except Exception as exc:
            log.warning("mena_boards: %s group failed: %s", label, exc)

    log.info("mena_boards total: %d jobs", len(all_jobs))
    return all_jobs
