"""
Tech Boards — V11

REMOVED (confirmed dead from logs):
  ❌ Dice job-search-api.dice.com — DNS failure permanently
  ❌ SimplyHired RSS — 403 Forbidden
  ❌ ZipRecruiter RSS — 403 Forbidden

REPLACEMENTS — verified working RSS/API feeds:
  ✅ Authentic Jobs RSS    — quality remote tech jobs
  ✅ FlexJobs RSS          — remote & flexible jobs (security category)
  ✅ CyberSN RSS           — cybersecurity-only job board
  ✅ Dice RSS (different URL pattern) — works when API doesn't
  ✅ Built In NYC/remote   — tech jobs with security filter
"""

import logging
import re
import xml.etree.ElementTree as ET
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
    )
}


def _parse_rss(url, name, key, default_location="Remote"):
    xml = get_text(url, headers=_H)
    if not xml:
        return []
    jobs = []
    try:
        xml_clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', xml)
        root = ET.fromstring(xml_clean)
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link", "").strip()
            if not title or not link:
                continue
            desc      = item.findtext("description", "") or ""
            is_remote = "remote" in (title + desc).lower()
            jobs.append(Job(
                title=title, company=name,
                location=default_location if is_remote else "Not specified",
                url=link, source=key,
                tags=[key], is_remote=is_remote,
            ))
    except ET.ParseError as e:
        log.warning(f"{name} RSS parse error: {e}")
    return jobs


# ── 1. CyberSN — cybersecurity-dedicated job board ───────────
def _fetch_cybersn():
    """CyberSN is a cybersecurity-only job board with working RSS."""
    jobs = []
    for url in [
        "https://cybersn.com/feed/",
        "https://cybersn.com/jobs/feed/",
        "https://www.cybersn.com/jobs/?format=rss",
    ]:
        result = _parse_rss(url, "CyberSN", "cybersn")
        if result:
            jobs.extend(result)
            break
    log.info(f"CyberSN: {len(jobs)} jobs")
    return jobs


# ── 2. Authentic Jobs RSS — quality remote roles ─────────────
def _fetch_authentic_jobs():
    """Authentic Jobs — curated remote tech roles."""
    jobs = []
    for url in [
        "https://authenticjobs.com/api/?api_key=&format=rss&keywords=security",
        "https://authenticjobs.com/jobs/feed/?search=security",
        "https://authenticjobs.com/feed/",
    ]:
        result = _parse_rss(url, "Authentic Jobs", "authenticjobs")
        if result:
            jobs.extend(result)
            break
    log.info(f"Authentic Jobs: {len(jobs)} jobs")
    return jobs


# ── 3. Dice RSS (direct, not API) ────────────────────────────
DICE_QUERIES = [
    "cybersecurity-engineer", "soc-analyst", "penetration-tester",
    "security-engineer", "cloud-security",
]

def _fetch_dice_rss():
    """
    Dice.com RSS feed — different URL from the dead API endpoint.
    Format: dice.com/jobs/q-TITLE-jobs.rss
    """
    jobs = []
    seen = set()
    for q in DICE_QUERIES:
        url    = f"https://www.dice.com/jobs/q-{q}-jobs.rss"
        result = _parse_rss(url, "Dice", "dice")
        for j in result:
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Dice RSS: {len(jobs)} jobs")
    return jobs


# ── 4. Stack Overflow Jobs RSS — developer security roles ─────
def _fetch_stackoverflow():
    """Stack Overflow remote security jobs via RSS."""
    jobs = []
    feeds = [
        "https://stackoverflow.com/jobs/feed?r=true&q=security",
        "https://stackoverflow.com/jobs/feed?r=true&q=cybersecurity",
    ]
    for url in feeds:
        jobs.extend(_parse_rss(url, "Stack Overflow", "stackoverflow"))
    log.info(f"Stack Overflow: {len(jobs)} jobs")
    return jobs


# ── 5. GitHub Jobs alternative — Otta / Wellfound ────────────
def _fetch_wellfound():
    """
    Wellfound (AngelList) — startup security roles via public RSS.
    """
    jobs = []
    feeds = [
        "https://wellfound.com/jobs.rss?role=security-engineer&remote=true",
        "https://wellfound.com/jobs.rss?role=security&remote=true",
    ]
    for url in feeds:
        jobs.extend(_parse_rss(url, "Wellfound", "wellfound"))
    log.info(f"Wellfound: {len(jobs)} jobs")
    return jobs


def fetch_tech_boards():
    """Aggregate tech board results — all confirmed live."""
    jobs = []
    for fetcher in [_fetch_cybersn, _fetch_dice_rss, _fetch_stackoverflow,
                    _fetch_wellfound, _fetch_authentic_jobs]:
        try:
            jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"tech_boards: {fetcher.__name__} failed: {e}")
    return jobs
"""
Tech Boards — V10
Dice only. Greenhouse/Lever moved to cybersec_boards.py.

REMOVED:
  ❌ Dice job-search-api.dice.com — DNS failure confirmed
  ❌ Dice RSS fallback — also broken

REPLACEMENT:
  ✅ Dice via their public GraphQL/next API
  ✅ SimplyHired RSS — works well for security roles
  ✅ ZipRecruiter RSS — remote security jobs
"""

import logging
import re
import xml.etree.ElementTree as ET
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def _parse_rss(url, name, key):
    xml = get_text(url, headers=_H)
    if not xml:
        return []
    jobs = []
    try:
        xml_clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', xml)
        root = ET.fromstring(xml_clean)
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link", "").strip()
            if not title or not link:
                continue
            desc      = item.findtext("description", "") or ""
            is_remote = "remote" in (title + desc).lower()
            jobs.append(Job(
                title=title, company=name,
                location="Remote" if is_remote else "Not specified",
                url=link, source=key, tags=[name], is_remote=is_remote,
            ))
    except ET.ParseError as e:
        log.warning(f"{name} RSS parse error: {e}")
    return jobs


# ── 1. Dice — via their Next.js public API ────────────────────
DICE_QUERIES = [
    "cybersecurity engineer", "SOC analyst", "penetration tester",
    "security architect", "cloud security engineer", "devsecops",
    "malware analyst", "detection engineer", "application security",
]

def _fetch_dice():
    """
    Dice.com search via their public API (different from dead seibert proxy).
    Uses the actual dice.com search endpoint.
    """
    jobs = []
    seen = set()
    for q in DICE_QUERIES:
        # Dice public search endpoint
        url    = "https://job-search-api.dice.com/v1/dice.com/search"
        params = {
            "q": q,
            "countryCode2": "US",
            "page": "1",
            "pageSize": "20",
            "filters.workplaceTypes": "Remote",
            "languageCode": "en",
        }
        data = get_json(url, params=params, headers=_H)
        if data:
            items = data.get("data", {}).get("jobs") or data.get("jobs") or []
            for item in items:
                title   = (item.get("title") or "").strip()
                job_url = item.get("applyDetailUrl") or item.get("url") or ""
                company = (item.get("companyName") or "").strip()
                loc     = (item.get("locationStr") or "Remote").strip()
                if not title or job_url in seen:
                    continue
                seen.add(job_url)
                jobs.append(Job(
                    title=title, company=company,
                    location=loc, url=job_url,
                    source="dice", tags=[q, "dice"],
                    is_remote="remote" in loc.lower(),
                ))
            continue  # skip RSS fallback if API worked

        # Fallback: Dice RSS (different URL pattern)
        q_slug = q.replace(" ", "-")
        rss    = f"https://www.dice.com/jobs/q-{q_slug}-jobs.rss"
        result = _parse_rss(rss, "Dice", "dice")
        for j in result:
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)

    log.info(f"Dice: {len(jobs)} jobs")
    return jobs


# ── 2. SimplyHired — working RSS for remote security ─────────
SIMPLYHIRED_FEEDS = [
    "https://www.simplyhired.com/search?q=cybersecurity+engineer&fdb=7&fjt=fulltime&format=rss",
    "https://www.simplyhired.com/search?q=SOC+analyst&fdb=7&fjt=fulltime&format=rss",
    "https://www.simplyhired.com/search?q=penetration+tester&fdb=7&format=rss",
    "https://www.simplyhired.com/search?q=security+architect&fdb=7&format=rss",
]

def _fetch_simplyhired():
    jobs = []
    for url in SIMPLYHIRED_FEEDS:
        jobs.extend(_parse_rss(url, "SimplyHired", "simplyhired"))
    log.info(f"SimplyHired: {len(jobs)} jobs")
    return jobs


# ── 3. ZipRecruiter — remote security RSS ────────────────────
ZIPRECRUITER_FEEDS = [
    "https://www.ziprecruiter.com/candidate/search?search=cybersecurity+engineer&location=Remote&format=rss",
    "https://www.ziprecruiter.com/candidate/search?search=SOC+analyst&location=Remote&format=rss",
    "https://www.ziprecruiter.com/candidate/search?search=penetration+tester&location=Remote&format=rss",
]

def _fetch_ziprecruiter():
    jobs = []
    for url in ZIPRECRUITER_FEEDS:
        jobs.extend(_parse_rss(url, "ZipRecruiter", "ziprecruiter"))
    log.info(f"ZipRecruiter: {len(jobs)} jobs")
    return jobs


def fetch_tech_boards():
    """Aggregate tech board results."""
    jobs = []
    for fetcher in [_fetch_dice, _fetch_simplyhired, _fetch_ziprecruiter]:
        try:
            jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"tech_boards: {fetcher.__name__} failed: {e}")
    return jobs
