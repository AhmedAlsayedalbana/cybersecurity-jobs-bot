"""Priority source wrappers (no-login only)."""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET

import config
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

_SECURITY_TERMS = [
    "cybersecurity", "cyber security", "information security",
    "soc", "security engineer", "security analyst", "grc",
    "penetration", "pentest", "threat", "dfir", "appsec",
    "cloud security", "network security",
]
_SECURITY_TERMS = config.sanitize_keywords(_SECURITY_TERMS, min_len=3)


def _is_security(text: str) -> bool:
    t = (text or "").lower()
    return any(term in t for term in _SECURITY_TERMS)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def fetch_wuzzuf_priority() -> list[Job]:
    from sources.regional_boards import _fetch_wuzzuf_html  # local import by design
    return _fetch_wuzzuf_html()


def fetch_bayt_public() -> list[Job]:
    jobs: list[Job] = []
    seen: set[str] = set()
    urls = [
        "https://www.bayt.com/en/egypt/jobs/cyber-security-jobs/",
        "https://www.bayt.com/en/saudi-arabia/jobs/cyber-security-jobs/",
        "https://www.bayt.com/en/uae/jobs/cyber-security-jobs/",
    ]
    for url in urls:
        html = get_text(url, headers=_H, timeout=10, max_retries=1)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html,
            re.IGNORECASE | re.DOTALL,
        ):
            try:
                data = json.loads(block.strip())
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") != "JobPosting":
                    continue
                title = _clean_text(item.get("title", ""))
                if not title or not _is_security(title):
                    continue
                link = item.get("url", "")
                if not link or link in seen:
                    continue
                seen.add(link)
                org = item.get("hiringOrganization", {})
                company = org.get("name", "Bayt Employer") if isinstance(org, dict) else "Bayt Employer"
                location = "Gulf"
                loc = item.get("jobLocation", {})
                if isinstance(loc, dict):
                    addr = loc.get("address", {})
                    if isinstance(addr, dict):
                        location = addr.get("addressCountry", location)
                jobs.append(Job(
                    title=title,
                    company=company,
                    location=location,
                    url=link,
                    source="bayt",
                    source_key="bayt",
                    content_type="job_listing",
                    origin_priority=41,
                    tags=["bayt", "priority2"],
                ))
    log.info(f"Priority Bayt: {len(jobs)} jobs")
    return jobs


def fetch_naukrigulf_public() -> list[Job]:
    from sources.gulf_expanded import _fetch_naukrigulf  # local import
    try:
        jobs = _fetch_naukrigulf()
        for j in jobs:
            j.source_key = "naukrigulf"
            j.content_type = "job_listing"
            j.origin_priority = 42
        return jobs
    except Exception:
        return []


def fetch_indeed_public() -> list[Job]:
    jobs: list[Job] = []
    seen: set[str] = set()
    queries = [
        ("cyber security", "Egypt"),
        ("soc analyst", "Saudi Arabia"),
        ("information security", "United Arab Emirates"),
    ]
    for q, loc in queries:
        url = (
            "https://www.indeed.com/jobs?"
            + urllib.parse.urlencode({"q": q, "l": loc, "fromage": "3"})
        )
        html = get_text(url, headers=_H, timeout=10, max_retries=1)
        if not html:
            continue
        for href, title in re.findall(
            r'<a[^>]+href="(/viewjob\?[^"]+)"[^>]*aria-label="([^"]+)"',
            html,
            re.IGNORECASE,
        ):
            title = _clean_text(title)
            if not title or not _is_security(title):
                continue
            link = urllib.parse.urljoin("https://www.indeed.com", href)
            if link in seen:
                continue
            seen.add(link)
            jobs.append(Job(
                title=title,
                company="Indeed Employer",
                location=loc,
                url=link,
                source="indeed",
                source_key="indeed",
                content_type="job_listing",
                origin_priority=43,
                tags=["indeed", "priority2"],
            ))
    log.info(f"Priority Indeed: {len(jobs)} jobs")
    return jobs


def fetch_company_career_pages() -> list[Job]:
    from sources.egypt_companies import fetch_egypt_companies
    rows = fetch_egypt_companies()
    for row in rows:
        row.source_key = "company_careers"
        row.content_type = "job_listing"
        row.origin_priority = 51
    return rows


def fetch_google_intelligence() -> list[Job]:
    from sources.google_jobs import fetch_google_jobs
    rows = fetch_google_jobs()
    for row in rows:
        row.source_key = "google_intel"
        row.content_type = "job_listing"
        row.origin_priority = 52
    return rows


def fetch_telegram_channels() -> list[Job]:
    from sources.new_sources import _fetch_telegram_public_channels
    rows = _fetch_telegram_public_channels()
    for row in rows:
        row.source_key = "telegram_channels"
        row.content_type = "job_listing"
        row.origin_priority = 61
    return rows


def fetch_reddit_discord() -> list[Job]:
    from sources.new_sources import _fetch_hackernews_hiring, _fetch_github_security_jobs
    rows = _fetch_hackernews_hiring() + _fetch_github_security_jobs()
    for row in rows:
        row.source_key = "reddit_discord"
        row.content_type = "job_listing"
        row.origin_priority = 62
    return rows


def fetch_upwork_public() -> list[Job]:
    jobs: list[Job] = []
    rss = get_text("https://research.upwork.com/freelance-jobs/rss/", headers=_H, timeout=10, max_retries=1)
    if not rss:
        return jobs
    try:
        root = ET.fromstring(rss)
    except ET.ParseError:
        return jobs
    seen: set[str] = set()
    for item in root.findall(".//item"):
        title = _clean_text(item.findtext("title", ""))
        link = _clean_text(item.findtext("link", ""))
        desc = _clean_text(item.findtext("description", ""))
        if not title or not link or link in seen:
            continue
        if not _is_security(f"{title} {desc}"):
            continue
        seen.add(link)
        jobs.append(Job(
            title=title,
            company="Upwork Client",
            location="Remote",
            url=link,
            source="upwork",
            source_key="upwork",
            content_type="job_listing",
            origin_priority=71,
            description=desc[:500],
            is_remote=True,
            job_type="Freelance",
            tags=["upwork", "priority-freelance"],
        ))
    log.info(f"Priority Upwork: {len(jobs)} jobs")
    return jobs


def fetch_freelancer_priority() -> list[Job]:
    from sources.regional_boards import _fetch_freelancer_security
    rows = _fetch_freelancer_security()
    for row in rows:
        row.source_key = "freelancer"
        row.origin_priority = 72
    return rows


def fetch_mostaql_priority() -> list[Job]:
    from sources.regional_boards import _fetch_mostaql_rss
    rows = _fetch_mostaql_rss()
    for row in rows:
        row.source_key = "mostaql"
        row.origin_priority = 73
    return rows


def fetch_khamsat_priority() -> list[Job]:
    from sources.freelance import _fetch_khamsat
    rows = _fetch_khamsat()
    for row in rows:
        row.source_key = "khamsat"
        row.origin_priority = 74
    return rows


def fetch_fiverr_public() -> list[Job]:
    jobs: list[Job] = []
    seen: set[str] = set()
    url = "https://www.fiverr.com/search/gigs?query=cybersecurity"
    html = get_text(url, headers=_H, timeout=10, max_retries=1)
    if not html:
        return jobs
    for href, title in re.findall(r'href="(/[^"]+)"[^>]*>\s*<[^>]*>([^<]{6,120})<', html, re.IGNORECASE):
        title = _clean_text(title)
        if not title or not _is_security(title):
            continue
        link = urllib.parse.urljoin("https://www.fiverr.com", href)
        if link in seen:
            continue
        seen.add(link)
        jobs.append(Job(
            title=title,
            company="Fiverr Seller",
            location="Remote",
            url=link,
            source="fiverr",
            source_key="fiverr",
            content_type="job_listing",
            origin_priority=75,
            is_remote=True,
            job_type="Freelance",
            tags=["fiverr", "priority-freelance"],
        ))
        if len(jobs) >= 25:
            break
    log.info(f"Priority Fiverr: {len(jobs)} jobs")
    return jobs
