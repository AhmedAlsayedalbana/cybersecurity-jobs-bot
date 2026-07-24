"""Direct Egyptian job-board integrations for v51.

These sources replace the dead MENA board bundle and fail closed: a
blocked/changed website returns an empty list without delaying the whole run.
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET

from models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

_H = {
    "User-Agent": "Mozilla/5.0 (compatible; cybersec-jobbot/51.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _parse_dt(raw: str) -> datetime:
    if not raw:
        return datetime.utcnow()
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:31], fmt)
        except ValueError:
            continue
    return datetime.utcnow()


def _job(
    *,
    title: str,
    company: str,
    location: str,
    url: str,
    source: str,
    description: str = "",
    posted_date: datetime | None = None,
    priority: int = 999,
) -> Job | None:
    title = _clean(title)
    url = (url or "").strip()
    if not title or not url:
        return None
    return Job(
        title=title,
        company=_clean(company) or "Egypt Employer",
        location=_clean(location) or "Egypt",
        url=url,
        source=source,
        source_key=source,
        description=_clean(description)[:500],
        posted_date=posted_date or datetime.utcnow(),
        geo_hint="egypt",
        origin_priority=priority,
        tags=[source, "egypt_direct"],
    )


def _retag(jobs: list[Job], source: str, priority: int, tag: str) -> list[Job]:
    for job in jobs:
        job.source = source
        job.source_key = source
        job.origin_priority = priority
        job.geo_hint = "egypt"
        tags = list(getattr(job, "tags", []) or [])
        job.tags = list(dict.fromkeys(tags + [source, tag, "egypt_direct"]))
    return jobs


def fetch_wuzzuf_rss() -> list[Job]:
    """Wuzzuf direct Egypt source; uses HTML fallback when RSS is unavailable."""
    queries = ["cybersecurity", "information security", "امن معلومات"]
    jobs: list[Job] = []
    seen: set[str] = set()
    for q in queries:
        url = "https://wuzzuf.net/search/jobs/feed/?" + urllib.parse.urlencode({"q": q, "l": "Egypt"})
        try:
            resp = requests.get(url, timeout=15, headers=_H)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
        except Exception as exc:
            log.debug("Wuzzuf RSS %s unavailable: %s", q, exc)
            continue
        for item in root.findall(".//item"):
            link = _clean(item.findtext("link", ""))
            if not link or link in seen:
                continue
            seen.add(link)
            job = _job(
                title=item.findtext("title", ""),
                company="Wuzzuf Employer",
                location="Egypt",
                url=link,
                source="wuzzuf_rss",
                description=item.findtext("description", ""),
                posted_date=_parse_dt(item.findtext("pubDate", "")),
                priority=16,
            )
            if job:
                jobs.append(job)
    if not jobs:
        try:
            from sources.regional_boards import _fetch_wuzzuf_html
            jobs = _retag(_fetch_wuzzuf_html(), "wuzzuf_rss", 16, "wuzzuf_html_fallback")
        except Exception as exc:
            log.debug("Wuzzuf HTML fallback unavailable: %s", exc)
    log.info("Wuzzuf RSS: %d jobs", len(jobs))
    return jobs


def fetch_bayt_egypt() -> list[Job]:
    """Bayt Egypt pages, parsed from JSON-LD JobPosting blocks."""
    jobs: list[Job] = []
    seen: set[str] = set()
    queries = ["cyber-security", "information-security", "network-security", "soc-analyst"]
    for q in queries:
        url = f"https://www.bayt.com/en/egypt/jobs/{q}-jobs/"
        try:
            resp = requests.get(url, timeout=15, headers=_H)
            if resp.status_code != 200:
                log.debug("Bayt Egypt %s: HTTP %s", q, resp.status_code)
                continue
        except Exception as exc:
            log.debug("Bayt Egypt %s unavailable: %s", q, exc)
            continue
        for blob in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', resp.text, re.S | re.I):
            try:
                data = json.loads(blob.strip())
            except Exception:
                continue
            for item in data if isinstance(data, list) else [data]:
                if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                    continue
                link = item.get("url", "")
                if not link or link in seen:
                    continue
                seen.add(link)
                org = item.get("hiringOrganization") or {}
                loc = item.get("jobLocation") or {}
                addr = loc.get("address", {}) if isinstance(loc, dict) else {}
                job = _job(
                    title=item.get("title", ""),
                    company=org.get("name", "") if isinstance(org, dict) else "",
                    location=addr.get("addressLocality", "Egypt") if isinstance(addr, dict) else "Egypt",
                    url=link,
                    source="bayt_egypt",
                    description=item.get("description", ""),
                    posted_date=_parse_dt(item.get("datePosted", "")),
                    priority=17,
                )
                if job:
                    jobs.append(job)
    if not jobs:
        try:
            from sources.jina_scraper import _BoardSpec, _parse_board
            fallback = _parse_board(_BoardSpec(
                "https://www.bayt.com/en/egypt/jobs/cyber-security-jobs/",
                "Bayt Egypt",
                "egypt",
                20,
            ))
            jobs = _retag(fallback, "bayt_egypt", 17, "jina_fallback")
        except Exception as exc:
            log.debug("Bayt Egypt Jina fallback unavailable: %s", exc)
    log.info("Bayt Egypt: %d jobs", len(jobs))
    return jobs


def fetch_careers_egypt() -> list[Job]:
    """EgyTech.fyi public jobs API."""
    jobs: list[Job] = []
    data = get_json(
        "https://api.egytech.fyi/jobs?title=security&page=1&limit=30",
        timeout=12,
        headers={**_H, "Accept": "application/json"},
        max_retries=1,
    )
    if not isinstance(data, dict):
        log.debug("EgyTech.fyi public API unavailable or returned invalid JSON")
        return jobs
    for item in data.get("data", []) if isinstance(data, dict) else []:
        job = _job(
            title=item.get("title", ""),
            company=item.get("company", ""),
            location=item.get("location", "Egypt"),
            url=item.get("url", ""),
            source="egytech_fyi",
            priority=18,
        )
        if job:
            jobs.append(job)
    log.info("EgyTech.fyi: %d jobs", len(jobs))
    return jobs
