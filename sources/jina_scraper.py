"""
sources/jina_scraper.py — v46
Jina AI Reader + fallback scraper for job boards that block regular HTTP.

Jina Reader (r.jina.ai) converts any URL to clean markdown — works even
on JS-heavy sites and anti-bot pages. No API key needed for basic usage.

Supports:
  • Bayt.com (Egypt + Gulf)
  • NaukriGulf.com
  • Gulftalent.com
  • Tanqeeb.com (Arabic Gulf board)
  • Forasna.com (Egypt)
  • Wuzzuf fallback (when HTML scraper blocked)

Usage:
    from sources.jina_scraper import fetch_jina_boards
    jobs = fetch_jina_boards()
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime
from typing import NamedTuple

from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

SOURCE_NAME = "jina_scraper"

_JINA_BASE = "https://r.jina.ai"
_ENABLED = os.getenv("ENABLE_JINA_SCRAPER", "true").lower() in ("1", "true", "yes")

_JINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CyberJobsBot/1.0)",
    "Accept": "text/markdown, text/plain, */*",
    "X-Return-Format": "markdown",
    "X-No-Cache": "true",
}


class _BoardSpec(NamedTuple):
    url: str
    site_name: str
    geo_hint: str
    max_jobs: int = 20


_BOARDS: list[_BoardSpec] = [
    # Gulf — proven working via Jina ─────────────────────────────────────
    _BoardSpec(
        "https://www.bayt.com/en/egypt/jobs/cyber-security-jobs/",
        "Bayt Egypt", "egypt", 20,
    ),
    _BoardSpec(
        "https://www.bayt.com/en/saudi-arabia/jobs/cyber-security-jobs/",
        "Bayt Saudi", "gulf", 20,
    ),
    _BoardSpec(
        "https://www.bayt.com/en/uae/jobs/cyber-security-jobs/",
        "Bayt UAE", "gulf", 15,
    ),
    _BoardSpec(
        "https://www.naukrigulf.com/cyber-security-jobs",
        "NaukriGulf", "gulf", 25,
    ),
    _BoardSpec(
        "https://www.naukrigulf.com/information-security-jobs-in-saudi-arabia",
        "NaukriGulf KSA", "gulf", 20,
    ),
    _BoardSpec(
        "https://www.gulftalent.com/jobs/cybersecurity",
        "GulfTalent", "gulf", 20,
    ),
    # Akhtaboot — MENA board via Jina ────────────────────────────────────
    _BoardSpec(
        "https://www.akhtaboot.com/en/jobs?keywords=cybersecurity&country%5B%5D=EG",
        "Akhtaboot Egypt", "egypt", 20,
    ),
    _BoardSpec(
        "https://www.akhtaboot.com/en/jobs?keywords=cybersecurity&country%5B%5D=SA",
        "Akhtaboot KSA", "gulf", 20,
    ),
    # DrJobPro via Jina ──────────────────────────────────────────────────
    _BoardSpec(
        "https://drjobpro.com/jobs/cybersecurity-jobs/egypt",
        "DrJobPro Egypt", "egypt", 20,
    ),
    _BoardSpec(
        "https://drjobpro.com/jobs/cybersecurity-jobs/saudi-arabia",
        "DrJobPro KSA", "gulf", 15,
    ),
    # Tanqeeb — Gulf ────────────────────────────────────────────────────
    _BoardSpec(
        "https://tanqeeb.com/jobs?q=cybersecurity&country=SA",
        "Tanqeeb KSA", "gulf", 15,
    ),
]

# Job link patterns per site
_LINK_PATTERNS: dict[str, str] = {
    "bayt.com":         r"https://www\.bayt\.com/en/[a-z-]+/jobs/[^\s\)\"']+",
    "naukrigulf.com":   r"https://www\.naukrigulf\.com/[^\s\)\"']+",
    "gulftalent.com":   r"https://www\.gulftalent\.com/[^\s\)\"']+",
    "tanqeeb.com":      r"https://tanqeeb\.com/job/[^\s\)\"']+",
    "akhtaboot.com":    r'href="(/en/job/\d+/[^"]+)"',
    "drjobpro.com":     r'href="(https://drjobpro\.com/jobs/[^"]+)"',
}


def _fetch_via_jina(url: str) -> str:
    """Fetch a URL via Jina AI Reader and return markdown text."""
    jina_url = f"{_JINA_BASE}/{url}"
    return get_text(jina_url, headers=_JINA_HEADERS, timeout=20, max_retries=1) or ""


def _extract_job_links(markdown: str, site_name: str, base_url: str) -> list[str]:
    """Extract job links from Jina markdown output."""
    domain = re.search(r"https?://([^/]+)", base_url)
    if not domain:
        return []
    domain_key = domain.group(1).lstrip("www.")
    base_origin = f"https://{domain.group(1)}"

    # Try domain-specific pattern first
    for key, pattern in _LINK_PATTERNS.items():
        if key in domain_key:
            found = re.findall(pattern, markdown)
            # Convert relative links to absolute
            absolute = []
            for link in dict.fromkeys(found):
                if link.startswith("/"):
                    link = base_origin + link
                absolute.append(link)
            return absolute

    # Generic markdown link pattern: [text](url)
    found = re.findall(r"\[([^\]]+)\]\((https?://[^\)]+)\)", markdown)
    return [url for _, url in found if domain_key in url]


def _extract_job_title_from_link(link: str, markdown: str, site_name: str) -> str:
    """Try to extract job title from markdown near the link."""
    # Look for markdown link pattern: [TITLE](link)
    m = re.search(r"\[([^\]]{5,120})\]\(" + re.escape(link) + r"\)", markdown)
    if m:
        return m.group(1).strip()

    # Look for heading before the link
    lines = markdown.split("\n")
    for i, line in enumerate(lines):
        if link in line:
            for j in range(max(0, i-3), i):
                if lines[j].startswith("#") or len(lines[j].strip()) > 10:
                    return lines[j].strip("# ").strip()
    return ""


def _parse_board(spec: _BoardSpec) -> list[Job]:
    markdown = _fetch_via_jina(spec.url)
    if not markdown or len(markdown) < 200:
        log.debug("Jina: empty response for %s", spec.site_name)
        return []

    links = _extract_job_links(markdown, spec.site_name, spec.url)
    if not links:
        log.debug("Jina: no job links found for %s", spec.site_name)
        return []

    jobs: list[Job] = []
    for link in links[:spec.max_jobs]:
        title = _extract_job_title_from_link(link, markdown, spec.site_name)
        if not title or len(title) < 4:
            # Try fetching the job page via Jina for the title
            try:
                job_md = _fetch_via_jina(link)
                m = re.search(r"^#\s+(.+)$", job_md, re.MULTILINE)
                if m:
                    title = m.group(1).strip()
                time.sleep(0.3)   # polite
            except Exception:
                pass

        if not title or len(title) < 4:
            continue

        # ✅ v46: Reject titles that look like page headings or nav items, not job titles
        _title_check = title.lower().strip()
        _JINA_GARBAGE_PATTERNS = [
            "jobs in ", "jobs -", "information security jobs",
            "cybersecurity jobs", "security jobs in",
            "by country", "by city", "by category", "search jobs",
            "popular search", "login", "sign in",
            "part time jobs", "fresher jobs", "airport jobs",
            "marketing jobs", "teaching jobs", "civil engineering jobs",
            "sales jobs", "admin jobs", "hr jobs", "finance jobs",
            "doctor jobs", "construction jobs", "public health jobs",
            "optometrist jobs", "food beverage jobs", "biochemistry jobs",
            "neom jobs", "africa jobs", "erbil jobs", "shutdown jobs",
        ]
        if any(pat in _title_check for pat in _JINA_GARBAGE_PATTERNS):
            log.debug(f"Jina: skipping nav/page title: {title[:60]}")
            continue
        if _title_check.endswith(" jobs") and not any(
            signal in _title_check
            for signal in ["security", "cyber", "soc", "grc", "pentest", "forensic"]
        ):
            log.debug(f"Jina: skipping generic job category: {title[:60]}")
            continue

        # ✅ v46: Reject titles that are too long (likely page descriptions, not job titles)
        if len(title) > 150:
            continue

        is_remote = "remote" in (title + " " + spec.url).lower()

        jobs.append(Job(
            title=title,
            company=spec.site_name,
            location=spec.geo_hint.replace("egypt", "Egypt").replace("gulf", "Gulf"),
            url=link,
            source=SOURCE_NAME,
            is_remote=is_remote,
            geo_hint=spec.geo_hint,
            original_source=f"Jina / {spec.site_name}",
            tags=["jina", spec.site_name.lower().replace(" ", "_")],
        ))

    return jobs


def fetch_jina_boards() -> list[Job]:
    """Scrape job boards via Jina AI Reader.

    Returns raw Job objects for Bot1's intelligence pipeline.
    Disabled by default — enable with ENABLE_JINA_SCRAPER=true.
    """
    if not _ENABLED:
        log.debug("jina_scraper: disabled (ENABLE_JINA_SCRAPER=false)")
        return []

    all_jobs: list[Job] = []
    for spec in _BOARDS:
        try:
            batch = _parse_board(spec)
            all_jobs.extend(batch)
            if batch:
                log.info("Jina / %s: %d jobs", spec.site_name, len(batch))
            time.sleep(1.0)   # Jina rate-limit courtesy
        except Exception as exc:
            log.warning("jina_scraper: %s failed: %s", spec.site_name, exc)

    log.info("Jina total: %d raw jobs", len(all_jobs))
    return all_jobs
