"""
LinkedIn primary fetcher (async-first).

Highlights:
- Native `aiohttp` async fetch (search + details).
- Pagination depth for Egypt/Gulf priority queries.
- Early dedup by LinkedIn job ID before detail fetch.
- LI_AT cookie is used when available.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
from datetime import datetime, timedelta

import config
from models import Job, extract_salary_from_text
from sources.linkedin_common import FRESH_TPR, linkedin_get_text

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

try:
    import aiohttp
except Exception:  # pragma: no cover - safe fallback when aiohttp unavailable
    aiohttp = None


def _q(keywords: str, location: str = "", remote: bool = False) -> dict:
    row = {"keywords": keywords}
    if location:
        row["location"] = location
    if remote:
        row["f_WT"] = "2"
    return row


EGYPT_CORE = [
    _q("cybersecurity", "Cairo, Egypt"),
    _q("SOC analyst", "Cairo, Egypt"),
    _q("security engineer", "Cairo, Egypt"),
    _q("penetration tester", "Egypt"),
    _q("information security", "Egypt"),
    _q("GRC analyst", "Egypt"),
    _q("cloud security", "Egypt"),
    _q("application security", "Egypt"),
]

GULF_CORE = [
    _q("cybersecurity", "Riyadh, Saudi Arabia"),
    _q("SOC analyst", "Saudi Arabia"),
    _q("security engineer", "Saudi Arabia"),
    _q("cybersecurity", "Dubai, United Arab Emirates"),
    _q("SOC analyst", "United Arab Emirates"),
    _q("GRC analyst", "United Arab Emirates"),
    _q("cybersecurity", "Qatar"),
    _q("cybersecurity", "Kuwait"),
]

REMOTE_CORE = [
    _q("cybersecurity engineer", remote=True),
    _q("SOC analyst", remote=True),
    _q("penetration tester", remote=True),
    _q("threat intelligence analyst", remote=True),
]

INTERNSHIP_CORE = [
    _q("cybersecurity internship", "Egypt"),
    _q("security trainee", "Egypt"),
    _q("cybersecurity internship", "Saudi Arabia"),
    _q("security trainee", "United Arab Emirates"),
]

ARABIC_CORE = [
    _q(" ", "Egypt"),
    _q(" ", "Egypt"),
    _q(" ", "Egypt"),
    _q(" ", "Saudi Arabia"),
]


def _build_search_plan() -> list[tuple[dict, list[int]]]:
    plan: list[tuple[dict, list[int]]] = []
    for row in (EGYPT_CORE + GULF_CORE)[:10]:
        plan.append((row, [0, 25, 50]))
    for row in (EGYPT_CORE + GULF_CORE)[10:]:
        plan.append((row, [0]))
    for row in INTERNSHIP_CORE + ARABIC_CORE + REMOTE_CORE:
        plan.append((row, [0]))
    return plan


def _extract_job_ids(html: str) -> list[str]:
    ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
    if not ids:
        ids = re.findall(r'"jobPostingId":(\d+)', html)
    if not ids:
        ids = re.findall(r"/jobs/view/(\d+)/", html)
    ordered: list[str] = []
    seen: set[str] = set()
    for jid in ids:
        if jid in seen:
            continue
        seen.add(jid)
        ordered.append(jid)
    return ordered


def _clean_html_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _extract(pattern: str, html: str, default: str = "") -> str:
    m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else default


def _extract_posted_date(html: str) -> datetime | None:
    lowered = (html or "").lower()
    m = re.search(r"(\d{1,2})\s*(minute|minutes|min|hour|hours|hr|day|days|d|week|weeks|w|month|months)\s+ago", lowered)
    if not m:
        return None
    amount = int(m.group(1))
    unit = m.group(2)
    now = datetime.now()
    if unit.startswith("min"):
        return now - timedelta(minutes=amount)
    if unit.startswith("hour") or unit == "hr":
        return now - timedelta(hours=amount)
    if unit.startswith("day") or unit == "d":
        return now - timedelta(days=amount)
    if unit.startswith("week") or unit == "w":
        return now - timedelta(weeks=amount)
    if unit.startswith("month"):
        return now - timedelta(days=amount * 30)
    return None


def _parse_detail(html: str, job_id: str) -> Job | None:
    title = _clean_html_text(
        _extract(r'<h2[^>]*class="[^"]*top-card-layout__title[^"]*"[^>]*>(.*?)</h2>', html)
    )
    if not title:
        title = _clean_html_text(_extract(r"<title>(.*?)</title>", html))
        title = re.sub(r"\s*\|\s*LinkedIn.*", "", title).strip()

    company = _clean_html_text(
        _extract(r'<a[^>]*class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)</a>', html)
    )
    if not company:
        company = _clean_html_text(
            _extract(r'<span[^>]*class="[^"]*topcard__flavor[^"]*"[^>]*>(.*?)</span>', html)
        )

    location = _clean_html_text(
        _extract(r'<span[^>]*class="[^"]*topcard__flavor--bullet[^"]*"[^>]*>(.*?)</span>', html)
    )
    if not location:
        location = "Not specified"

    desc_raw = _extract(r'<div[^>]*class="[^"]*(?:description|show-more-less-html)[^"]*"[^>]*>(.*?)</div>', html)
    description = _clean_html_text(desc_raw)[:1400]
    salary = extract_salary_from_text(f"{title} {description}")
    posted_date = _extract_posted_date(html)
    is_remote = bool(re.search(r"\bremote\b", f"{location} {description}", re.IGNORECASE))

    if not title:
        return None

    return Job(
        title=title,
        company=company or "Unknown",
        location=location,
        url=f"https://www.linkedin.com/jobs/view/{job_id}/",
        source="linkedin",
        salary=salary,
        tags=["linkedin", "primary", "aiohttp"],
        is_remote=is_remote,
        description=description,
        posted_date=posted_date,
    )


def _build_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Referer": "https://www.linkedin.com/jobs/",
        "Connection": "keep-alive",
    }


async def _fetch_text(
    session: "aiohttp.ClientSession",
    url: str,
    *,
    params: dict | None = None,
    retries: int = 2,
) -> str | None:
    for attempt in range(retries + 1):
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 429:
                    await asyncio.sleep((2 ** attempt) + random.uniform(0.2, 0.8))
                    continue
                if resp.status == 403:
                    return None
                if resp.status >= 400:
                    if attempt >= retries:
                        return None
                    await asyncio.sleep((2 ** attempt) + random.uniform(0.1, 0.6))
                    continue
                text = await resp.text()
                if text and len(text) > 120:
                    return text
        except Exception:
            if attempt >= retries:
                return None
        await asyncio.sleep((2 ** attempt) + random.uniform(0.2, 0.8))
    return None


async def fetch_linkedin_async() -> list[Job]:
    from config import LI_PRIMARY_BUDGET_SECONDS

    if aiohttp is None:
        return await asyncio.to_thread(fetch_linkedin)

    budget = LI_PRIMARY_BUDGET_SECONDS
    start_ts = time.time()
    plan = _build_search_plan()
    max_failures = 14
    failures = 0
    seen_job_ids: set[str] = set()
    jobs: list[Job] = []

    li_at = os.getenv("LI_AT", "").strip()
    cookies = {"li_at": li_at} if li_at else None
    if li_at:
        log.info("LinkedIn primary: LI_AT detected, authenticated session path active.")

    connector = aiohttp.TCPConnector(
        limit=max(20, config.LINKEDIN_ASYNC_MAX_CONCURRENCY * 2),
        ttl_dns_cache=300,
    )
    timeout = aiohttp.ClientTimeout(total=14)
    sem = asyncio.Semaphore(max(3, config.LINKEDIN_ASYNC_MAX_CONCURRENCY))

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers=_build_headers(),
        cookies=cookies,
    ) as session:
        for search, starts in plan:
            if (time.time() - start_ts) > budget:
                log.info(f"LinkedIn: budget {budget}s exhausted after {len(jobs)} jobs")
                break
            if failures >= max_failures:
                log.warning("LinkedIn: too many failures, stopping source early")
                break

            for page_start in starts:
                if (time.time() - start_ts) > budget:
                    break

                params = {
                    "keywords": search.get("keywords", ""),
                    "start": str(page_start),
                    "count": "25",
                    "f_TPR": FRESH_TPR,
                }
                if search.get("location"):
                    params["location"] = search["location"]
                if search.get("f_WT"):
                    params["f_WT"] = search["f_WT"]

                html = await _fetch_text(session, SEARCH_URL, params=params, retries=2)
                if not html:
                    failures += 1
                    continue

                job_ids = _extract_job_ids(html)
                if not job_ids and page_start > 0:
                    break

                new_ids = [jid for jid in job_ids if jid not in seen_job_ids][:20]
                for jid in new_ids:
                    seen_job_ids.add(jid)

                async def load_one(job_id: str) -> Job | None:
                    async with sem:
                        detail_html = await _fetch_text(
                            session,
                            DETAIL_URL.format(job_id=job_id),
                            retries=1,
                        )
                        if not detail_html:
                            return None
                        return _parse_detail(detail_html, job_id)

                detail_tasks = [load_one(job_id) for job_id in new_ids]
                if detail_tasks:
                    detail_rows = await asyncio.gather(*detail_tasks, return_exceptions=True)
                    for row in detail_rows:
                        if isinstance(row, Job):
                            jobs.append(row)

                await asyncio.sleep(random.uniform(0.08, 0.22))

    log.info(
        f"LinkedIn: fetched {len(jobs)} jobs. unique job_ids={len(seen_job_ids)} failures={failures}"
    )
    return jobs


def fetch_linkedin() -> list[Job]:
    """
    Sync compatibility wrapper used when source is executed outside async runtime.
    """
    if aiohttp is None:
        return _fetch_linkedin_sync_fallback()
    try:
        return asyncio.run(fetch_linkedin_async())
    except RuntimeError:
        # If called while loop is already running, use sync fallback safely.
        return _fetch_linkedin_sync_fallback()


def _fetch_linkedin_sync_fallback() -> list[Job]:
    """Fallback when aiohttp is unavailable."""
    from config import LI_PRIMARY_BUDGET_SECONDS

    budget = LI_PRIMARY_BUDGET_SECONDS
    start_ts = time.time()
    jobs: list[Job] = []
    seen_job_ids: set[str] = set()
    failures = 0

    for search, starts in _build_search_plan():
        if time.time() - start_ts > budget:
            break
        for page_start in starts:
            params = {
                "keywords": search.get("keywords", ""),
                "start": str(page_start),
                "count": "25",
                "f_TPR": FRESH_TPR,
            }
            if search.get("location"):
                params["location"] = search["location"]
            if search.get("f_WT"):
                params["f_WT"] = search["f_WT"]

            html = linkedin_get_text(SEARCH_URL, params=params)
            if not html:
                failures += 1
                continue
            for job_id in _extract_job_ids(html):
                if job_id in seen_job_ids:
                    continue
                seen_job_ids.add(job_id)
                detail_html = linkedin_get_text(DETAIL_URL.format(job_id=job_id))
                if not detail_html:
                    continue
                job = _parse_detail(detail_html, job_id)
                if job:
                    jobs.append(job)

    log.info(
        f"LinkedIn (sync fallback): fetched {len(jobs)} jobs. unique job_ids={len(seen_job_ids)} failures={failures}"
    )
    return jobs

