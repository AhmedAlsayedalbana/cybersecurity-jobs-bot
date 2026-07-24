"""Direct Gulf job-board integrations for v51."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import re
import time
import urllib.parse

import requests

from models import Job

log = logging.getLogger(__name__)

_H = {
    "User-Agent": "Mozilla/5.0 (compatible; cybersec-jobbot/51.0)",
    "Accept": "application/json,text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _parse_dt(raw: str) -> datetime:
    if not raw:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(raw[:19])
    except ValueError:
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
        company=_clean(company) or "Gulf Employer",
        location=_clean(location) or "Gulf",
        url=url,
        source=source,
        source_key=source,
        description=_clean(description)[:500],
        posted_date=posted_date or datetime.utcnow(),
        geo_hint="gulf",
        origin_priority=priority,
        tags=[source, "gulf_direct"],
    )


def fetch_gulftalent_api() -> list[Job]:
    """GulfTalent public search endpoint, with graceful 403/HTML fallback."""
    url = "https://www.gulftalent.com/api/v2/jobs?keyword=cybersecurity&country=&page=1"
    try:
        resp = requests.get(url, timeout=15, headers=_H)
        if resp.status_code != 200:
            log.debug("GulfTalent unavailable: HTTP %s", resp.status_code)
            return []
        data = resp.json()
    except Exception as exc:
        log.debug("GulfTalent unavailable: %s", exc)
        return []
    jobs: list[Job] = []
    for item in data.get("jobs", []) if isinstance(data, dict) else []:
        company = item.get("company", {})
        job = _job(
            title=item.get("title", ""),
            company=company.get("name", "") if isinstance(company, dict) else str(company or ""),
            location=item.get("location", "Gulf"),
            url=item.get("url", ""),
            source="gulftalent",
            description=item.get("description", ""),
            posted_date=_parse_dt(item.get("posted_date", "")),
            priority=45,
        )
        if job:
            jobs.append(job)
    log.info("GulfTalent Direct: %d jobs", len(jobs))
    return jobs


def fetch_naukrigulf_search() -> list[Job]:
    """NaukriGulf AJAX search for security roles."""
    jobs: list[Job] = []
    seen: set[str] = set()
    queries = ["cybersecurity", "information security", "SOC analyst", "network security", "penetration testing"]
    start = time.time()
    budget_seconds = 18
    for q in queries:
        if time.time() - start > budget_seconds:
            log.debug("NaukriGulf Direct: budget exhausted")
            break
        params = {"searchType": "typeahead", "keyword": q}
        url = "https://www.naukrigulf.com/cybersecurity-jobs?" + urllib.parse.urlencode(params)
        try:
            resp = requests.get(url, timeout=5, headers={**_H, "X-Requested-With": "XMLHttpRequest"})
            if resp.status_code != 200 or "application/json" not in resp.headers.get("Content-Type", ""):
                continue
            data = resp.json()
        except requests.Timeout as exc:
            log.debug("NaukriGulf %s timed out: %s", q, exc)
            break
        except Exception as exc:
            log.debug("NaukriGulf %s unavailable: %s", q, exc)
            continue
        for item in data.get("jobs", []) if isinstance(data, dict) else []:
            raw_url = item.get("jobUrl", "")
            link = urllib.parse.urljoin("https://www.naukrigulf.com", raw_url)
            if not link or link in seen:
                continue
            seen.add(link)
            job = _job(
                title=item.get("title", ""),
                company=item.get("company", ""),
                location=item.get("location", "Gulf"),
                url=link,
                source="naukrigulf",
                priority=46,
            )
            if job:
                jobs.append(job)
    log.info("NaukriGulf Direct: %d jobs", len(jobs))
    return jobs


def fetch_jobzella_gulf() -> list[Job]:
    """Jobzella Gulf search parsed from JSON-LD JobPosting blocks."""
    try:
        resp = requests.get(
            "https://www.jobzella.com/jobs?q=cybersecurity&country=ksa",
            timeout=12,
            headers=_H,
        )
        if resp.status_code != 200:
            log.debug("Jobzella unavailable: HTTP %s", resp.status_code)
            return []
    except Exception as exc:
        log.debug("Jobzella unavailable: %s", exc)
        return []
    jobs: list[Job] = []
    seen: set[str] = set()
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
            job = _job(
                title=item.get("title", ""),
                company=org.get("name", "") if isinstance(org, dict) else "",
                location="Gulf",
                url=link,
                source="jobzella",
                description=item.get("description", ""),
                posted_date=_parse_dt(item.get("datePosted", "")),
                priority=47,
            )
            if job:
                jobs.append(job)
    log.info("Jobzella Gulf: %d jobs", len(jobs))
    return jobs
