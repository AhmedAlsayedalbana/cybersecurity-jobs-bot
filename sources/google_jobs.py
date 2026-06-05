"""
Google Jobs � SerpAPI + Wuzzuf HTML fallback.
v31: Fixed duplicate code, added more Egyptian searches, added Wuzzuf direct scrape.
"""

import logging
import re
import os
from datetime import datetime, timedelta
import config
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
}

GOOGLE_JOBS_SEARCHES = [
    # Egypt � broad + specific roles
    {"q": "cybersecurity jobs Egypt",              "location": "Egypt",                        "gl": "eg"},
    {"q": "SOC analyst jobs Cairo Egypt",          "location": "Cairo, Egypt",                 "gl": "eg"},
    {"q": "penetration tester jobs Egypt",         "location": "Egypt",                        "gl": "eg"},
    {"q": "security engineer jobs Egypt",          "location": "Egypt",                        "gl": "eg"},
    {"q": "junior cybersecurity jobs Egypt",       "location": "Egypt",                        "gl": "eg"},
    {"q": "information security analyst Egypt",    "location": "Egypt",                        "gl": "eg"},
    {"q": "GRC analyst jobs Egypt",                "location": "Egypt",                        "gl": "eg"},
    {"q": "network security engineer Cairo",       "location": "Cairo, Egypt",                 "gl": "eg"},
    {"q": "cloud security engineer Egypt",         "location": "Egypt",                        "gl": "eg"},
    {"q": "DFIR analyst Egypt",                    "location": "Egypt",                        "gl": "eg"},
    {"q": "security analyst Alexandria Egypt",     "location": "Alexandria, Egypt",            "gl": "eg"},
    {"q": "cybersecurity New Administrative Capital", "location": "Egypt",                     "gl": "eg"},
    {"q": "cybersecurity Smart Village Egypt",     "location": "Egypt",                        "gl": "eg"},
    # Saudi Arabia
    {"q": "cybersecurity jobs Saudi Arabia",       "location": "Riyadh, Saudi Arabia",         "gl": "sa"},
    {"q": "SOC analyst Riyadh",                    "location": "Riyadh, Saudi Arabia",         "gl": "sa"},
    {"q": "security engineer Jeddah",              "location": "Jeddah, Saudi Arabia",         "gl": "sa"},
    # UAE
    {"q": "cybersecurity jobs Dubai",              "location": "Dubai, United Arab Emirates",  "gl": "ae"},
    {"q": "security analyst Abu Dhabi",            "location": "Abu Dhabi, United Arab Emirates", "gl": "ae"},
    {"q": "SOC analyst UAE",                       "location": "Dubai, United Arab Emirates",  "gl": "ae"},
    # Other Gulf
    {"q": "cybersecurity jobs Qatar",              "location": "Doha, Qatar",                  "gl": "qa"},
    {"q": "security engineer Kuwait",              "location": "Kuwait City, Kuwait",          "gl": "kw"},
]

_STRICT_CYBER_TERMS = config.sanitize_keywords([
    "cybersecurity", "cyber security", "information security", "infosec",
    "soc", "security operations", "threat intelligence", "incident response",
    "penetration", "pentest", "red team", "blue team",
    "application security", "appsec", "cloud security",
    "network security", "security engineer", "security analyst",
    "security architect", "grc", "vulnerability", "dfir",
], min_len=3)


def _is_strict_cyber_title(title: str) -> bool:
    t = (title or "").lower()
    return any(term in t for term in _STRICT_CYBER_TERMS)


def _parse_relative_age_to_dt(text: str) -> datetime | None:
    raw = (text or "").strip()
    lowered = raw.lower()
    m = re.search(r"(\d{1,3})\s*(minute|minutes|min|hour|hours|hr|day|days|d|week|weeks|w)\s+ago", lowered)
    if not m:
        # Try absolute ISO/DATE formats from JSON-LD datePosted.
        for candidate in (raw, raw.replace("Z", "+00:00")):
            try:
                dt = datetime.fromisoformat(candidate)
                return dt.replace(tzinfo=None)
            except Exception:
                continue
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(raw[:10], fmt)
            except Exception:
                continue
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
    return None


def _extract_serpapi_posted_date(item: dict) -> datetime | None:
    if not isinstance(item, dict):
        return None
    detected = item.get("detected_extensions") or {}
    hints: list[str] = []
    if isinstance(detected, dict):
        posted_at = detected.get("posted_at")
        if posted_at:
            hints.append(str(posted_at))
    exts = item.get("extensions")
    if isinstance(exts, list):
        hints.extend(str(x) for x in exts if x)
    for hint in hints:
        dt = _parse_relative_age_to_dt(hint)
        if dt:
            return dt
    return None


def _fetch_via_serpapi():
    if not SERPAPI_KEY:
        return []
    jobs = []
    seen_urls = set()
    _first_done = False
    for search in GOOGLE_JOBS_SEARCHES:
        q = (search.get("q") or "").strip()
        if not q:
            continue
        params = {
            "engine":   "google_jobs",
            "q":        q,
            "location": search.get("location", ""),
            "api_key":  SERPAPI_KEY,
            "hl":       "en",
            "gl":       search.get("gl", "us"),
        }
        data = get_json("https://serpapi.com/search", params=params, headers=HEADERS, max_retries=0)
        if not _first_done:
            _first_done = True
            if not data or "jobs_results" not in data:
                log.warning("SerpAPI: first request failed � skipping remaining")
                break
        if not data or "jobs_results" not in data:
            continue
        for item in data["jobs_results"]:
            title = (item.get("title") or "").strip()
            if not _is_strict_cyber_title(title):
                continue
            posted_date = _extract_serpapi_posted_date(item)
            if not posted_date:
                # Reliability-first policy: Google results without age signal are discarded.
                continue
            if datetime.now() - posted_date >= timedelta(hours=config.MAX_JOB_AGE_HOURS):
                continue
            url_job = ""
            for link in item.get("related_links", []):
                url_job = link.get("link", "")
                if url_job:
                    break
            if not url_job:
                url_job = ("https://www.google.com/search?q="
                           + search["q"].replace(" ", "+") + "&ibp=htl;jobs")
            if url_job in seen_urls:
                continue
            seen_urls.add(url_job)
            jobs.append(Job(
                title=title,
                company=item.get("company_name", "Unknown"),
                location=item.get("location", search.get("location", "")),
                url=url_job,
                source="google_jobs",
                description=(item.get("description") or "")[:300],
                tags=["google_jobs", search.get("gl", "")],
                is_remote="remote" in item.get("title", "").lower(),
                posted_date=posted_date,
            ))
    log.info(f"Google Jobs (SerpAPI): {len(jobs)} jobs")
    return jobs






def _fetch_wuzzuf_direct():
    """
    Wuzzuf.net � Egypt's top job board. Direct HTML scrape.
    v33: Added as primary Egypt source since SerpAPI/Adzuna consistently fail.
    """
    import json as _json
    jobs = []
    seen = set()
    searches = [
        ("cybersecurity",       "Egypt"),
        ("information security","Egypt"),
        ("SOC analyst",         "Egypt"),
        ("penetration tester",  "Egypt"),
        ("security engineer",   "Egypt"),
        ("GRC",                 "Egypt"),
        ("network security",    "Egypt"),
        ("cloud security",      "Egypt"),
    ]
    for query, location in searches:
        query = (query or "").strip()
        if not query:
            continue
        import urllib.parse as _up
        url = f"https://wuzzuf.net/search/jobs/?a=navbg&q={_up.quote(query)}&l=Egypt&sort=date"
        html = get_text(url, headers=HEADERS)
        if not html:
            continue
        # Extract JSON-LD job postings
        for block in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL):
            try:
                data = _json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title = item.get("title", "").strip()
                    if not title or title in seen or not _is_strict_cyber_title(title):
                        continue
                    date_posted = _parse_relative_age_to_dt(str(item.get("datePosted", "")))
                    if not date_posted:
                        # Reliability-first policy: require recency signal.
                        continue
                    if datetime.now() - date_posted >= timedelta(hours=config.MAX_JOB_AGE_HOURS):
                        continue
                    seen.add(title)
                    company = ""
                    org = item.get("hiringOrganization", {})
                    if isinstance(org, dict):
                        company = org.get("name", "Unknown")
                    loc_data = item.get("jobLocation", {})
                    if isinstance(loc_data, dict):
                        addr = loc_data.get("address", {})
                        loc_str = addr.get("addressLocality", "") or addr.get("addressCountry", "Egypt")
                    else:
                        loc_str = "Egypt"
                    jobs.append(Job(
                        title=title,
                        company=company,
                        location=loc_str or "Egypt",
                        url=item.get("url", url),
                        source="wuzzuf",
                        tags=["wuzzuf", "egypt"],
                        posted_date=date_posted,
                    ))
            except Exception:
                continue
        import time as _t; _t.sleep(1.5)
    log.info(f"Wuzzuf Direct: {len(jobs)} jobs")
    return jobs


def fetch_google_jobs():
    """Wuzzuf direct scraper only — SerpAPI disabled (persistent 429s)."""
    try:
        return _fetch_wuzzuf_direct()
    except Exception as e:
        log.warning(f"google_jobs _fetch_wuzzuf_direct failed: {e}")
        return []
