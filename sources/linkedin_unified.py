"""
Unified LinkedIn engine.

Goals:
- One controlled LinkedIn pipeline instead of overlapping fetchers.
- Priority lanes: HR posts -> core jobs -> expansion jobs.
- Central rate limiting + circuit breaker to reduce 429 storms.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import unescape

import config
from linkedin_url_utils import extract_linkedin_post_id
from models import Job, extract_salary_from_text
from sources.linkedin_common import FRESH_TPR
from sources.linkedin_hr_posts_scraper import fetch_linkedin_hr_posts_scraper

log = logging.getLogger(__name__)

_LINKEDIN_PARTIAL_RESULTS: list[Job] = []


def _geo_hint_from_query_location(query_location: str) -> str:
    """
    Derive a reliable geo_hint from the LinkedIn search query location string.
    This is AUTHORITATIVE — we know exactly which region's LinkedIn feed we queried.
    Returns: "egypt" | "gulf" | "global" | ""
    NOTE: Filters out empty-string patterns from config sets to avoid false matches
    (empty string is always a substring of any string).
    """
    if not query_location:
        return ""
    loc = query_location.lower()
    _eg = {p for p in config.EGYPT_PATTERNS if p.strip()}
    _gu = {p for p in config.GULF_PATTERNS if p.strip()}
    if any(x in loc for x in _eg):
        return "egypt"
    if any(x in loc for x in _gu):
        return "gulf"
    return "global"


SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

try:
    import aiohttp
except Exception:  # pragma: no cover
    aiohttp = None


@dataclass(slots=True)
class QuerySpec:
    keywords: str
    location: str = ""
    remote: bool = False
    pages: tuple[int, ...] = (0, 25, 50)
    priority: int = 100
    source_key: str = "linkedin_jobs"


CORE_QUERIES: list[QuerySpec] = [
    # ── Egypt core (highest volume) ──────────────────────────────────────────
    QuerySpec("cybersecurity", "Cairo, Egypt", pages=(0, 25, 50, 75), priority=10),
    QuerySpec("SOC analyst", "Cairo, Egypt", pages=(0, 25, 50), priority=11),
    QuerySpec("security engineer", "Egypt", pages=(0, 25, 50), priority=12),
    QuerySpec("penetration tester", "Egypt", pages=(0, 25), priority=13),
    QuerySpec("information security", "Egypt", pages=(0, 25), priority=14),
    QuerySpec("GRC analyst", "Egypt", pages=(0, 25), priority=15),
    QuerySpec("cybersecurity intern", "Egypt", pages=(0, 25), priority=16),
    # v53: new Egypt core queries
    QuerySpec("application security", "Egypt", pages=(0, 25), priority=17),
    QuerySpec("threat intelligence", "Egypt", pages=(0, 25), priority=17),
    QuerySpec("devsecops", "Egypt", pages=(0, 25), priority=18),
    QuerySpec("cloud security", "Egypt", pages=(0, 25), priority=18),
    QuerySpec("أمن سيبراني", "مصر", pages=(0, 25), priority=19),
    QuerySpec("أمن معلومات", "مصر", pages=(0, 25), priority=19),
]

GULF_QUERIES: list[QuerySpec] = [
    # ── Saudi Arabia ─────────────────────────────────────────────────────
    QuerySpec("cybersecurity", "Saudi Arabia", pages=(0, 25, 50), priority=20, source_key="linkedin_gulf"),
    QuerySpec("SOC analyst", "Saudi Arabia", pages=(0, 25), priority=21, source_key="linkedin_gulf"),
    QuerySpec("security engineer", "Riyadh", pages=(0, 25), priority=22, source_key="linkedin_gulf"),
    QuerySpec("penetration tester", "Saudi Arabia", pages=(0, 25), priority=23, source_key="linkedin_gulf"),
    QuerySpec("information security", "Riyadh", pages=(0, 25), priority=24, source_key="linkedin_gulf"),
    QuerySpec("GRC consultant", "Saudi Arabia", pages=(0,), priority=25, source_key="linkedin_gulf"),
    QuerySpec("cloud security", "Saudi Arabia", pages=(0,), priority=26, source_key="linkedin_gulf"),
    QuerySpec("security operations", "Saudi Arabia", pages=(0,), priority=27, source_key="linkedin_gulf"),
    QuerySpec("cybersecurity", "Jeddah", pages=(0,), priority=28, source_key="linkedin_gulf"),
    # ── UAE + Other Gulf ─────────────────────────────────────────────────
    QuerySpec("security engineer", "United Arab Emirates", pages=(0, 25), priority=30, source_key="linkedin_gulf"),
    QuerySpec("cybersecurity", "Dubai", pages=(0, 25), priority=31, source_key="linkedin_gulf"),
    QuerySpec("SOC analyst", "Dubai", pages=(0, 25), priority=32, source_key="linkedin_gulf"),
    QuerySpec("cloud security", "Abu Dhabi", pages=(0,), priority=33, source_key="linkedin_gulf"),
    QuerySpec("cybersecurity", "Qatar", pages=(0, 25), priority=34, source_key="linkedin_gulf"),
    QuerySpec("cybersecurity", "Kuwait", pages=(0,), priority=35, source_key="linkedin_gulf"),
    QuerySpec("information security", "Kuwait", pages=(0,), priority=36, source_key="linkedin_gulf"),
]

EXPANSION_QUERIES: list[QuerySpec] = [
    # ── Egypt expanded (v53: more coverage, Arabic terms, specific roles) ────
    QuerySpec("application security", "Egypt", pages=(0, 25), priority=40),
    QuerySpec("cloud security", "Egypt", pages=(0, 25), priority=41),
    QuerySpec("threat intelligence", "Egypt", pages=(0,), priority=42),
    QuerySpec("devsecops", "Egypt", pages=(0,), priority=43),
    QuerySpec("vulnerability management", "Egypt", pages=(0,), priority=44),
    QuerySpec("network security engineer", "Egypt", pages=(0,), priority=45),
    QuerySpec("CISO", "Egypt", pages=(0,), priority=46),
    # v53: Additional Egypt specializations
    QuerySpec("security architect", "Egypt", pages=(0,), priority=47),
    QuerySpec("malware analyst", "Egypt", pages=(0,), priority=48),
    QuerySpec("incident response", "Egypt", pages=(0,), priority=49),
    QuerySpec("digital forensics", "Egypt", pages=(0,), priority=50),
    QuerySpec("security auditor", "Egypt", pages=(0,), priority=51),
    QuerySpec("cyber analyst", "Cairo", pages=(0,), priority=52),
    QuerySpec("security consultant", "Egypt", pages=(0,), priority=53),
    # Arabic Egypt queries (v53: expanded)
    QuerySpec("أمن معلومات", "مصر", pages=(0,), priority=54),
    QuerySpec("أمن سيبراني", "القاهرة", pages=(0,), priority=55),
    QuerySpec("اختبار اختراق", "مصر", pages=(0,), priority=56),
    QuerySpec("محلل أمني", "مصر", pages=(0,), priority=57),
    # ── Egypt governorates (v53: target employees outside Cairo) ─────────────
    QuerySpec("cybersecurity", "Alexandria, Egypt", pages=(0,), priority=58),
    QuerySpec("information security", "Giza, Egypt", pages=(0,), priority=59),
    QuerySpec("security engineer", "Mansoura, Egypt", pages=(0,), priority=60),
    # ── Remote / Global ──────────────────────────────────────────────────────
    QuerySpec("cybersecurity engineer", remote=True, pages=(0, 25), priority=61, source_key="linkedin_remote"),
    QuerySpec("SOC analyst", remote=True, pages=(0, 25), priority=62, source_key="linkedin_remote"),
    QuerySpec("application security", remote=True, pages=(0,), priority=63, source_key="linkedin_remote"),
    QuerySpec("GRC analyst", remote=True, pages=(0,), priority=64, source_key="linkedin_remote"),
    QuerySpec("threat intelligence analyst", remote=True, pages=(0,), priority=65, source_key="linkedin_remote"),
    QuerySpec("penetration tester", remote=True, pages=(0,), priority=66, source_key="linkedin_remote"),
    QuerySpec("cloud security engineer", remote=True, pages=(0,), priority=67, source_key="linkedin_remote"),
    QuerySpec("devsecops engineer", remote=True, pages=(0,), priority=68, source_key="linkedin_remote"),
    QuerySpec("security researcher", remote=True, pages=(0,), priority=69, source_key="linkedin_remote"),
]

# Each specialty is searched separately in Egypt, Gulf, and remote lanes.
# Public LinkedIn result cards contain the title, company, location, and date,
# so several listing pages can be harvested without an extra request per job.
_SPECIALTY_PAGES = tuple(
    range(0, 25 * max(1, int(getattr(config, "LINKEDIN_PAGES_PER_QUERY", 4))), 25)
)
_SPECIALTY_KEYWORDS = (
    "cybersecurity", "SOC analyst", "IAM analyst", "application security",
    "DevSecOps engineer", "threat intelligence analyst", "red team", "GRC analyst",
    "bug bounty", "penetration tester",
)
CORE_QUERIES = [
    QuerySpec(keyword, "Egypt", pages=_SPECIALTY_PAGES, priority=10 + index)
    for index, keyword in enumerate(_SPECIALTY_KEYWORDS)
]
GULF_QUERIES = [
    QuerySpec("cybersecurity", "Saudi Arabia", pages=_SPECIALTY_PAGES, priority=20, source_key="linkedin_gulf"),
    QuerySpec("SOC analyst", "Riyadh", pages=_SPECIALTY_PAGES, priority=21, source_key="linkedin_gulf"),
    QuerySpec("IAM analyst", "Saudi Arabia", pages=_SPECIALTY_PAGES, priority=22, source_key="linkedin_gulf"),
    QuerySpec("application security", "United Arab Emirates", pages=_SPECIALTY_PAGES, priority=23, source_key="linkedin_gulf"),
    QuerySpec("DevSecOps engineer", "Riyadh", pages=_SPECIALTY_PAGES, priority=24, source_key="linkedin_gulf"),
    QuerySpec("threat intelligence analyst", "Dubai", pages=_SPECIALTY_PAGES, priority=25, source_key="linkedin_gulf"),
    QuerySpec("red team", "United Arab Emirates", pages=_SPECIALTY_PAGES, priority=26, source_key="linkedin_gulf"),
    QuerySpec("GRC analyst", "Saudi Arabia", pages=_SPECIALTY_PAGES, priority=27, source_key="linkedin_gulf"),
    QuerySpec("bug bounty", "Saudi Arabia", pages=_SPECIALTY_PAGES, priority=28, source_key="linkedin_gulf"),
    QuerySpec("penetration tester", "Dubai", pages=_SPECIALTY_PAGES, priority=29, source_key="linkedin_gulf"),
]
EXPANSION_QUERIES = [
    QuerySpec(keyword, remote=True, pages=_SPECIALTY_PAGES, priority=40 + index, source_key="linkedin_remote")
    for index, keyword in enumerate(_SPECIALTY_KEYWORDS)
]


class _RateLimiter:
    def __init__(self, max_rps: float):
        self._interval = max(0.0, 1.0 / max(0.05, max_rps))
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if now < self._next_allowed:
                await asyncio.sleep(self._next_allowed - now)
            self._next_allowed = time.monotonic() + self._interval + random.uniform(0.05, 0.25)


def _extract_job_ids(html: str) -> list[str]:
    ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
    if not ids:
        ids = re.findall(r'"jobPostingId":(\d+)', html)
    if not ids:
        ids = re.findall(r"/jobs/view/(\d+)/", html)
    out: list[str] = []
    seen: set[str] = set()
    for jid in ids:
        if jid in seen:
            continue
        seen.add(jid)
        out.append(jid)
    return out


def _clean_html_text(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


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


def _parse_listing_date(card_html: str) -> datetime | None:
    """Extract the verified posting date embedded in a LinkedIn result card."""
    raw = _extract(r'<time[^>]+datetime="([^"]+)"', card_html)
    if raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=None)
        except ValueError:
            pass
    return _extract_posted_date(card_html)


def _parse_listing_cards(
    html: str,
    *,
    source_key: str,
    origin_priority: int,
    geo_hint: str = "",
    remote_query: bool = False,
) -> list[Job]:
    """Turn public search-result cards into jobs without a detail-page fetch.

    The guest search response exposes every field needed by the strict
    publishing gate (title, company, location and date).  Falling back to a
    job-detail request is reserved for cards that cannot be parsed.
    """
    jobs: list[Job] = []
    seen: set[str] = set()
    for card in re.findall(r"<li\b[^>]*>.*?</li>", html or "", re.IGNORECASE | re.DOTALL):
        job_id = _extract(r'data-entity-urn="urn:li:jobPosting:(\d+)"', card)
        if not job_id or job_id in seen:
            continue
        title = _clean_html_text(
            _extract(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>(.*?)</h3>', card)
        )
        subtitle = _extract(r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>(.*?)</h4>', card)
        company = _clean_html_text(subtitle)
        location = _clean_html_text(
            _extract(r'<span[^>]*class="[^"]*job-search-card__location[^"]*"[^>]*>(.*?)</span>', card)
        )
        posted_date = _parse_listing_date(card)
        if not title or not company or not posted_date:
            continue
        seen.add(job_id)
        jobs.append(Job(
            title=title,
            company=company,
            location=location or "Not specified",
            url=f"https://www.linkedin.com/jobs/view/{job_id}/",
            source="linkedin_unified",
            source_key=source_key,
            tags=["linkedin", "unified", "listing_card"],
            is_remote=remote_query or bool(re.search(r"\bremote\b", location, re.IGNORECASE)),
            posted_date=posted_date,
            content_type="job_listing",
            origin_priority=origin_priority,
            geo_hint=geo_hint,
        ))
    return jobs


def _parse_detail(html: str, job_id: str, source_key: str, origin_priority: int, geo_hint: str = "") -> Job | None:
    title = _clean_html_text(_extract(r'<h2[^>]*class="[^"]*top-card-layout__title[^"]*"[^>]*>(.*?)</h2>', html))
    if not title:
        title = _clean_html_text(_extract(r"<title>(.*?)</title>", html))
        title = re.sub(r"\s*\|\s*LinkedIn.*", "", title).strip()
    if not title:
        return None

    company = _clean_html_text(_extract(r'<a[^>]*class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)</a>', html))
    if not company:
        company = _clean_html_text(_extract(r'<span[^>]*class="[^"]*topcard__flavor[^"]*"[^>]*>(.*?)</span>', html))
    location = _clean_html_text(_extract(r'<span[^>]*class="[^"]*topcard__flavor--bullet[^"]*"[^>]*>(.*?)</span>', html))
    desc_raw = _extract(r'<div[^>]*class="[^"]*(?:description|show-more-less-html)[^"]*"[^>]*>(.*?)</div>', html)
    description = _clean_html_text(desc_raw)[:1400]
    posted_date = _extract_posted_date(html)
    is_remote = bool(re.search(r"\bremote\b", f"{location} {description}", re.IGNORECASE))

    return Job(
        title=title,
        company=company or "Unknown",
        location=location or "Not specified",
        url=f"https://www.linkedin.com/jobs/view/{job_id}/",
        source="linkedin_unified",
        source_key=source_key,
        salary=extract_salary_from_text(f"{title} {description}"),
        tags=["linkedin", "unified"],
        is_remote=is_remote,
        description=description,
        posted_date=posted_date,
        content_type="job_listing",
        origin_priority=origin_priority,
        geo_hint=geo_hint,
    )


async def _fetch_text(
    session: "aiohttp.ClientSession",
    limiter: _RateLimiter,
    url: str,
    *,
    params: dict | None = None,
    max_retries: int = 3,
    circuit_state: dict | None = None,
) -> str | None:
    if circuit_state and circuit_state.get("open_until", 0.0) > time.time():
        await asyncio.sleep(0.4)
        return None

    for attempt in range(max_retries + 1):
        await limiter.acquire()
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 429:
                    if circuit_state is not None:
                        circuit_state["429"] = int(circuit_state.get("429", 0)) + 1
                        if circuit_state["429"] >= 5:
                            circuit_state["open_until"] = time.time() + 30
                            circuit_state["429"] = 0
                    await asyncio.sleep((2 ** attempt) + random.uniform(0.2, 1.0))
                    continue
                if resp.status >= 400:
                    if resp.status == 403:
                        return None
                    await asyncio.sleep((2 ** attempt) + random.uniform(0.1, 0.6))
                    continue
                text = await resp.text()
                if text and len(text) > 120:
                    return text
        except Exception:
            if attempt >= max_retries:
                return None
        await asyncio.sleep((2 ** attempt) + random.uniform(0.2, 0.8))
    return None


def _strict_filter_hr_posts(items: list[Job]) -> list[Job]:
    out: list[Job] = []
    for job in items:
        canonical = job.canonical_url
        post_id = extract_linkedin_post_id(canonical)
        if not post_id:
            continue
        job.source = "linkedin_unified"
        job.source_key = "linkedin_hr_posts"
        job.content_type = "hr_post"
        job.origin_priority = 5
        out.append(job)
    return out


async def _fetch_linkedin_unified_impl() -> list[Job]:
    global _LINKEDIN_PARTIAL_RESULTS
    budget_seconds = config.LINKEDIN_TOTAL_BUDGET_SECONDS
    start_ts = time.time()
    all_jobs: list[Job] = []
    _LINKEDIN_PARTIAL_RESULTS = all_jobs

    # Priority lane 1: real HR posts only.
    if config.ENABLE_SOURCE_LINKEDIN_HR_POSTS:
        hr_raw = await asyncio.to_thread(fetch_linkedin_hr_posts_scraper)
        hr_posts = _strict_filter_hr_posts(hr_raw)
        if config.ENABLE_STRICT_HR_POSTS_ONLY:
            all_jobs.extend(hr_posts)
        else:
            all_jobs.extend(hr_raw)
        log.info(f"LinkedIn unified: HR posts accepted={len(hr_posts)} raw={len(hr_raw)}")
    else:
        log.info("LinkedIn unified: HR posts disabled by ENABLE_SOURCE_LINKEDIN_HR_POSTS=false")

    if aiohttp is None:
        return all_jobs

    limiter = _RateLimiter(config.LINKEDIN_RATE_MAX_RPS)
    sem = asyncio.Semaphore(max(1, config.LINKEDIN_MAX_CONCURRENCY))
    circuit_state: dict[str, float | int] = {"429": 0, "open_until": 0.0}
    li_at = os.getenv("LI_AT", "").strip()
    cookies = {"li_at": li_at} if li_at else None
    if li_at:
        log.info("LinkedIn unified: LI_AT cookie detected (authenticated mode).")

    connector = aiohttp.TCPConnector(limit=max(4, config.LINKEDIN_MAX_CONCURRENCY * 2), ttl_dns_cache=300)
    timeout = aiohttp.ClientTimeout(total=16)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Referer": "https://www.linkedin.com/jobs/",
    }

    plan = CORE_QUERIES + GULF_QUERIES + EXPANSION_QUERIES
    seen_ids: set[str] = set()
    results_lock = asyncio.Lock()
    # v54: queries used to run one-at-a-time, which meant the 56-query plan
    # routinely blew through the whole time budget and returned only a
    # handful of partial jobs. The shared _RateLimiter below still serializes
    # every actual HTTP call at the same safe RPS, so running several queries
    # concurrently just removes dead idle time between independent branches
    # — it does NOT increase real request rate against LinkedIn.
    query_sem = asyncio.Semaphore(max(1, config.LINKEDIN_QUERY_CONCURRENCY))

    async def _run_query(session: "aiohttp.ClientSession", query: QuerySpec) -> None:
        if time.time() - start_ts > budget_seconds:
            return
        async with query_sem:
            empty_page_streak = 0
            query_new = 0
            for page_start in query.pages:
                if time.time() - start_ts > budget_seconds:
                    break
                params = {
                    "keywords": query.keywords,
                    "start": str(page_start),
                    "count": "25",
                    "f_TPR": FRESH_TPR,
                }
                if query.location:
                    params["location"] = query.location
                if query.remote:
                    params["f_WT"] = "2"

                html = await _fetch_text(
                    session,
                    limiter,
                    SEARCH_URL,
                    params=params,
                    max_retries=3,
                    circuit_state=circuit_state,
                )
                if not html:
                    continue

                job_ids = _extract_job_ids(html)
                if not job_ids:
                    empty_page_streak += 1
                    if empty_page_streak >= 2:
                        break
                    continue
                empty_page_streak = 0

                card_jobs = _parse_listing_cards(
                    html,
                    source_key=query.source_key,
                    origin_priority=query.priority,
                    geo_hint=_geo_hint_from_query_location(query.location),
                    remote_query=query.remote,
                )
                card_ids = {
                    job.url.rsplit("/", 2)[-2]
                    for job in card_jobs
                    if job.url.rsplit("/", 2)[-2].isdigit()
                }

                async with results_lock:
                    fresh_cards = [
                        job for job in card_jobs
                        if job.url.rsplit("/", 2)[-2] not in seen_ids
                    ]
                    for job in fresh_cards:
                        seen_ids.add(job.url.rsplit("/", 2)[-2])
                    # Detail requests are now a compatibility fallback only
                    # for cards whose structured fields were incomplete.
                    detail_limit = max(1, int(getattr(config, "LINKEDIN_DETAILS_PER_QUERY", 6)))
                    new_ids = [
                        jid for jid in job_ids
                        if jid not in seen_ids and jid not in card_ids
                    ][:detail_limit]
                    for jid in new_ids:
                        seen_ids.add(jid)
                    all_jobs.extend(fresh_cards)
                    query_new += len(fresh_cards)

                async def _load_one(job_id: str) -> Job | None:
                    async with sem:
                        detail_html = await _fetch_text(
                            session,
                            limiter,
                            DETAIL_URL.format(job_id=job_id),
                            max_retries=2,
                            circuit_state=circuit_state,
                        )
                        if not detail_html:
                            return None
                        return _parse_detail(
                            detail_html,
                            job_id=job_id,
                            source_key=query.source_key,
                            origin_priority=query.priority,
                            geo_hint=_geo_hint_from_query_location(query.location),
                        )

                if new_ids:
                    rows = await asyncio.gather(*[_load_one(jid) for jid in new_ids], return_exceptions=True)
                    async with results_lock:
                        for row in rows:
                            if isinstance(row, Job):
                                all_jobs.append(row)
                                query_new += 1
                await asyncio.sleep(random.uniform(0.12, 0.35))

                # Early stop for low-yield deep pages.
                if page_start >= 50 and query_new < 4:
                    break

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers=headers,
        cookies=cookies,
    ) as session:
        await asyncio.gather(*[_run_query(session, query) for query in plan], return_exceptions=True)

    log.info(f"LinkedIn unified: collected {len(all_jobs)} jobs/posts total")
    return all_jobs


async def fetch_linkedin_unified_async() -> list[Job]:
    budget = int(getattr(config, "LINKEDIN_TOTAL_BUDGET_SECONDS", 180))
    try:
        return await asyncio.wait_for(_fetch_linkedin_unified_impl(), timeout=budget)
    except asyncio.TimeoutError:
        log.warning(
            "LinkedIn Unified: hard timeout after %ss - returning %d partial results",
            budget,
            len(_LINKEDIN_PARTIAL_RESULTS),
        )
        return list(_LINKEDIN_PARTIAL_RESULTS)


def fetch_linkedin_unified() -> list[Job]:
    if aiohttp is None:
        if not config.ENABLE_SOURCE_LINKEDIN_HR_POSTS:
            return []
        hr_raw = fetch_linkedin_hr_posts_scraper()
        hr_posts = _strict_filter_hr_posts(hr_raw)
        return hr_posts if config.ENABLE_STRICT_HR_POSTS_ONLY else hr_raw
    try:
        return asyncio.run(fetch_linkedin_unified_async())
    except RuntimeError:
        return []
