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
from sources.http_utils import get_json, get_text

log = logging.getLogger(__name__)

# v80: shared wall-clock guard — sequential board reads must never exceed the
# orchestrator ceiling, or already-found candidates die with the thread.
_FETCH_BUDGET_SECONDS = 38.0


def _reader_html(url: str) -> str:
    """v80: public-reader rescue for Cloudflare-challenged boards (Wuzzuf /
    Bayt return 403 to direct GETs but often answer the reader's IP pool)."""
    try:
        return get_text(
            f"https://r.jina.ai/{url}",
            headers={"Accept": "text/html", "X-Respond-With": "markdown"},
            timeout=12, max_retries=0,
        ) or ""
    except Exception:
        return ""

_H = {
    "User-Agent": "Mozilla/5.0 (compatible; cybersec-jobbot/51.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _parse_dt(raw: str) -> datetime | None:
    # v80: honest None on failure — the old utcnow() fallback faked freshness
    # (+6) for every dateless board row, outranking genuinely fresh LinkedIn
    # postings and breaking the 70% LI contract.
    if not raw:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:31], fmt)
        except ValueError:
            continue
    return None


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
    # v80: dateless stays None (see _parse_dt) — neutral score, ranked last.
    return Job(
        title=title,
        company=_clean(company) or "Egypt Employer",
        location=_clean(location) or "Egypt",
        url=url,
        source=source,
        source_key=source,
        description=_clean(description)[:500],
        posted_date=posted_date,
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


def _parse_rss_items(xml_text: str, *, source: str, priority: int) -> list[Job]:
    """Parse an RSS/Atom feed body into jobs (shared direct+reader path)."""
    jobs: list[Job] = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return jobs
    seen: set[str] = set()
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
            source=source,
            description=item.findtext("description", ""),
            posted_date=_parse_dt(item.findtext("pubDate", "")),
            priority=priority,
        )
        if job:
            jobs.append(job)
    return jobs


def fetch_wuzzuf_rss() -> list[Job]:
    """Wuzzuf Egypt: RSS feed direct, public-reader rescue on 403 (v80).

    The /search/jobs/feed/ endpoint 403s direct GETs (Cloudflare) but is a
    static feed, so the reader pool usually answers it.
    """
    import time as _time
    queries = ["cybersecurity", "information security", "امن معلومات"]
    jobs: list[Job] = []
    _deadline = _time.monotonic() + _FETCH_BUDGET_SECONDS
    for q in queries:
        if _time.monotonic() >= _deadline:
            break
        url = "https://wuzzuf.net/search/jobs/feed/?" + urllib.parse.urlencode({"q": q, "l": "Egypt"})
        xml_text = get_text(url, headers=_H, timeout=10, max_retries=0)
        if not xml_text:
            xml_text = _reader_html(url)
        if not xml_text:
            log.debug("Wuzzuf RSS %s unavailable (direct+reader)", q)
            continue
        jobs.extend(_parse_rss_items(xml_text, source="wuzzuf_rss", priority=16))
    if not jobs:
        try:
            from sources.regional_boards import _fetch_wuzzuf_html
            jobs = _retag(_fetch_wuzzuf_html(), "wuzzuf_rss", 16, "wuzzuf_html_fallback")
        except Exception as exc:
            log.debug("Wuzzuf HTML fallback unavailable: %s", exc)
    log.info("Wuzzuf RSS: %d jobs", len(jobs))
    return jobs


def fetch_bayt_egypt() -> list[Job]:
    """Bayt Egypt pages, parsed from JSON-LD JobPosting blocks (v80: direct +
    public-reader rescue — Bayt 403s direct GETs)."""
    import time as _time
    jobs: list[Job] = []
    seen: set[str] = set()
    queries = ["cyber-security", "information-security", "network-security", "soc-analyst"]
    _deadline = _time.monotonic() + _FETCH_BUDGET_SECONDS
    for q in queries:
        if _time.monotonic() >= _deadline:
            break
        url = f"https://www.bayt.com/en/egypt/jobs/{q}-jobs/"
        html = get_text(url, headers=_H, timeout=10, max_retries=0)
        if not html:
            html = _reader_html(url)
        if not html:
            log.debug("Bayt Egypt %s unavailable (direct+reader)", q)
            continue
        for blob in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S | re.I):
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
