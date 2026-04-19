"""
Expanded Job Sources — v25
Based on log analysis (2026-04-16) — dead sources removed.

CONFIRMED WORKING:
  ✅ Greenhouse Tier1 Big Tech: 305 jobs
     (minus: snowflake 404, digitalocean 404)
  ✅ Greenhouse SaaS: 49 jobs
     (minus: docker, sentry, segment, zapier, plaid, ramp, rippling, deel — all 404)
  ✅ Greenhouse AI/Sec: 8 jobs
     (most dead, kept working subset)
  ✅ Hacker News Hiring: 8 jobs

ALL DEAD (removed from this file):
  ❌ Lever API (all 30 companies): HTTP 404 — entire Lever v0 API dead
  ❌ YC Jobs workatastartup.com: HTTP 404
  ❌ Sequoia Talent: 0 jobs
  ❌ 500 Global Jobs: 0 jobs
  ❌ Jobspresso: 0 jobs
  ❌ Outsourcely: DNS failure (site dead)
  ❌ Nodesk: HTTP 404
  ❌ Reddit JSON: HTTP 403
  ❌ Stack Overflow Jobs: HTTP 404 (shut down)
  ❌ CyberSeek API: HTTP 404
  ❌ Akhtaboot: 0 jobs
  ❌ NaukriGulf: Read timeout (10s x all requests)
  ❌ GulfTalent: 0 jobs
  ❌ Wuzzuf expanded: 0 jobs
  ❌ LinkedIn Egypt expanded: 0 jobs (rate limited)
  ❌ Gulf LinkedIn (Aramco etc): mostly 404
"""

import logging
import re
import json
import time
import xml.etree.ElementTree as ET
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}

SEC_KW = [
    "cybersecurity", "security analyst", "soc", "penetration", "pentest",
    "information security", "network security", "security engineer",
    "grc", "dfir", "cloud security", "devsecops", "malware", "forensic",
    "security architect", "security manager", "cyber", "infosec",
    "threat", "vulnerability", "appsec", "red team", "blue team",
    "siem", "soar", "endpoint security", "zero trust", "iam",
    "incident response", "compliance", "risk", "audit",
    "أمن معلومات", "أمن سيبراني",
]

def _is_sec(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in SEC_KW)

def _fetch_greenhouse_api(slug: str, company_name: str) -> list:
    """Fetch security jobs from a single Greenhouse board."""
    jobs = []
    url  = f"https://api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    data = get_json(url, headers=_H)
    if not data or "jobs" not in data:
        return jobs
    for item in data["jobs"]:
        title = item.get("title", "")
        if not _is_sec(title):
            continue
        job_url = item.get("absolute_url", "")
        if not job_url:
            continue
        loc      = item.get("location", {})
        location = loc.get("name", "") if isinstance(loc, dict) else ""
        jobs.append(Job(
            title=title, company=company_name,
            location=location or "Not specified",
            url=job_url, source="greenhouse_expanded",
            tags=["greenhouse", company_name.lower().replace(" ", "_")],
            is_remote="remote" in location.lower(),
        ))
    return jobs


def _fetch_lever_api(slug: str, company_name: str) -> list:
    """
    Fetch security jobs from jobs.lever.co public page.
    Lever v0 API is dead (404). Using the public HTML embed instead.
    """
    jobs = []
    # jobs.lever.co/{slug} returns JSON-LD or structured HTML
    url = f"https://jobs.lever.co/{slug}"
    html = get_text(url, headers=_H)
    if not html:
        return jobs
    import re
    # Extract job postings from Lever's HTML structure
    # Each posting: <a class="posting-title" href="URL">...
    links = re.findall(r'href="(https://jobs\.lever\.co/' + re.escape(slug) + r'/[a-f0-9\-]+)"', html)
    titles = re.findall(r'<h5[^>]*>(.*?)</h5>', html)
    locations = re.findall(r'<span class="location">(.*?)</span>', html)

    for i, link in enumerate(links[:20]):  # cap at 20 per company
        title = titles[i].strip() if i < len(titles) else ""
        if not title or not _is_sec(title):
            continue
        location = locations[i].strip() if i < len(locations) else "Not specified"
        jobs.append(Job(
            title=title, company=company_name,
            location=location or "Not specified",
            url=link, source="lever_expanded",
            tags=["lever", company_name.lower().replace(" ", "_")],
            is_remote="remote" in (location or "").lower(),
        ))
    return jobs


# ══════════════════════════════════════════════════════════════
# GREENHOUSE — Confirmed working slugs only (404s removed)
# ══════════════════════════════════════════════════════════════

# Tier 1A — Big Tech (confirmed working from v25 logs: 274 jobs)
# Removed: snowflake (404), digitalocean (404)
GREENHOUSE_TIER1 = [
    # Big Tech & Cloud
    ("stripe",        "Stripe"),
    ("airbnb",        "Airbnb"),
    ("lyft",          "Lyft"),
    ("dropbox",       "Dropbox"),
    ("figma",         "Figma"),
    ("mongodb",       "MongoDB"),
    ("datadog",       "Datadog"),
    ("cloudflare",    "Cloudflare"),
    ("coinbase",      "Coinbase"),
    ("robinhood",     "Robinhood"),
    ("pinterest",     "Pinterest"),
    ("reddit",        "Reddit"),
    ("instacart",     "Instacart"),
    ("databricks",    "Databricks"),
    ("elastic",       "Elastic"),
    ("asana",         "Asana"),
    ("squarespace",   "Squarespace"),
    ("fastly",        "Fastly"),
    ("twitch",        "Twitch"),
    ("duolingo",      "Duolingo"),
    ("hubspot",       "HubSpot"),
            ]

# Tier 1B — SaaS
GREENHOUSE_SAAS = [
    ("gitlab",        "GitLab"),
    ("postman",       "Postman"),
    ("twilio",        "Twilio"),
    ("brex",          "Brex"),
    ("gusto",         "Gusto"),
    ("remote",        "Remote.com"),
    ("lattice",       "Lattice"),
    ("intercom",      "Intercom"),
    ("mercury",       "Mercury"),
    ("algolia",       "Algolia"),
        ("okta",          "Okta"),
        ("bitwarden",     "Bitwarden"),
    ("netlify",       "Netlify"),
        ("airtable",      "Airtable"),
    ]

# Tier 1C — Cybersecurity focused
GREENHOUSE_AI_SEC = [
    ("abnormalsecurity", "Abnormal Security"),
    ("orca",             "Orca Security"),
    ("huntress",         "Huntress"),
    ("axonius",          "Axonius"),
    ("exabeam",          "Exabeam"),
    ("zscaler",          "Zscaler"),
                            ("torq",             "Torq"),
    ]

# Tier 1D — Lever API (major security vendors)
LEVER_COMPANIES = [
    ("crowdstrike",      "CrowdStrike"),
    ("sentinelone",      "SentinelOne"),
    ("rapid7",           "Rapid7"),
    ("tenable",          "Tenable"),
    ("qualys",           "Qualys"),
    ("darktrace",        "Darktrace"),
    ("recordedfuture",   "Recorded Future"),
    ("threatlocker",     "ThreatLocker"),
    ("vectra",           "Vectra AI"),
    ("illumio",          "Illumio"),
    ("intezer",          "Intezer"),
    ("horizon3ai",       "Horizon3.ai"),
]


def _fetch_greenhouse_tier1() -> list:
    jobs = []
    for slug, name in GREENHOUSE_TIER1:
        try:
            jobs.extend(_fetch_greenhouse_api(slug, name))
        except Exception as e:
            log.debug(f"Greenhouse Tier1 {name}: {e}")
    log.info(f"Greenhouse Tier1 (Big Tech): {len(jobs)} jobs")
    return jobs


def _fetch_greenhouse_saas() -> list:
    jobs = []
    for slug, name in GREENHOUSE_SAAS:
        try:
            jobs.extend(_fetch_greenhouse_api(slug, name))
        except Exception as e:
            log.debug(f"Greenhouse SaaS {name}: {e}")
    log.info(f"Greenhouse SaaS: {len(jobs)} jobs")
    return jobs


def _fetch_greenhouse_ai_sec() -> list:
    jobs = []
    for slug, name in GREENHOUSE_AI_SEC:
        try:
            jobs.extend(_fetch_greenhouse_api(slug, name))
        except Exception as e:
            log.debug(f"Greenhouse AI/Sec {name}: {e}")
    log.info(f"Greenhouse AI/Security: {len(jobs)} jobs")
    return jobs


def _fetch_lever_security() -> list:
    """Lever API — major security vendors."""
    jobs = []
    for slug, name in LEVER_COMPANIES:
        try:
            jobs.extend(_fetch_lever_api(slug, name))
        except Exception as e:
            log.debug(f"Lever {name}: {e}")
    log.info(f"Lever Security Companies: {len(jobs)} jobs")
    return jobs


# ══════════════════════════════════════════════════════════════
# COMMUNITY SOURCES (confirmed working)
# ══════════════════════════════════════════════════════════════

def _fetch_hackernews_hiring() -> list:
    """HN 'Who is hiring?' via Algolia — 8 jobs confirmed in logs."""
    jobs = []
    seen = set()
    search_url = (
        "https://hn.algolia.com/api/v1/search?"
        "query=Ask+HN+Who+is+hiring&tags=ask_hn&hitsPerPage=3"
    )
    data = get_json(search_url, headers=_H)
    if not data or not data.get("hits"):
        return jobs
    thread_id = data["hits"][0].get("objectID", "")
    if not thread_id:
        return jobs
    cdata = get_json(
        f"https://hn.algolia.com/api/v1/search?tags=comment,story_{thread_id}&hitsPerPage=100",
        headers=_H
    )
    if not cdata:
        return jobs
    for hit in cdata.get("hits", []):
        text = re.sub(r'<[^>]+>', ' ', hit.get("comment_text", "") or "").strip()
        if len(text) < 30 or not _is_sec(text):
            continue
        first_line = text.split('\n')[0][:120].strip()
        if not first_line or first_line in seen:
            continue
        seen.add(first_line)
        url_m   = re.search(r'https?://[^\s<>"]+', text)
        job_url = url_m.group(0) if url_m else f"https://news.ycombinator.com/item?id={hit.get('objectID','')}"
        co_m    = re.match(r'^([A-Za-z0-9\.\-& ]{2,40}?)\s*[\|,\(]', first_line)
        company = co_m.group(1).strip() if co_m else "HN Company"
        jobs.append(Job(
            title=first_line, company=company,
            location="Remote / Worldwide", url=job_url,
            source="hackernews_hiring",
            description=text[:300],
            tags=["hackernews", "hiring"],
            is_remote=True,
        ))
    log.info(f"Hacker News Hiring: {len(jobs)} jobs")
    return jobs


def _fetch_infosec_jobs_board() -> list:
    """
    infosec-jobs.com — cybersecurity-only job board with RSS feed.
    Confirmed working: returns real security jobs globally.
    """
    import xml.etree.ElementTree as ET
    jobs = []
    seen = set()
    feeds = [
        "https://infosec-jobs.com/feed/",
        "https://infosec-jobs.com/?s=soc+analyst&feed=rss2",
        "https://infosec-jobs.com/?s=penetration+tester&feed=rss2",
        "https://infosec-jobs.com/?s=security+engineer&feed=rss2",
        "https://infosec-jobs.com/?s=grc&feed=rss2",
    ]
    for feed_url in feeds:
        xml_text = get_text(feed_url, headers=_H)
        if not xml_text:
            continue
        try:
            root = ET.fromstring(xml_text)
            for item in root.findall(".//item"):
                title   = (item.findtext("title") or "").strip()
                url     = (item.findtext("link") or "").strip()
                desc    = (item.findtext("description") or "").strip()
                if not title or not url or url in seen:
                    continue
                if not _is_sec(title):
                    continue
                seen.add(url)
                # Extract location from description if present
                loc_match = __import__("re").search(
                    r'(?:location|located)[:\s]+([A-Za-z ,]+)',
                    desc, __import__("re").IGNORECASE
                )
                location = loc_match.group(1).strip() if loc_match else "Not specified"
                is_remote = "remote" in (title + desc).lower()
                if is_remote:
                    location = "Remote / Worldwide"
                jobs.append(Job(
                    title=title, company="InfoSec-Jobs",
                    location=location,
                    url=url, source="infosec_jobs_board",
                    description=desc[:300],
                    tags=["infosec-jobs", "cybersecurity"],
                    is_remote=is_remote,
                ))
        except Exception as e:
            log.debug(f"infosec-jobs parse error ({feed_url}): {e}")
    log.info(f"InfoSec Jobs board: {len(jobs)} jobs")
    return jobs


# ══════════════════════════════════════════════════════════════
# MAIN AGGREGATOR
# ══════════════════════════════════════════════════════════════

def fetch_expanded_sources() -> list:
    """
    Expanded sources v30 — Greenhouse (62 companies) + Lever (12 vendors) + community.
    """
    BUDGET_SECONDS = 8 * 60
    _start = time.time()
    all_jobs = []

    fetchers = [
        # ── Greenhouse Career Pages (highest quality) ─────────
        ("Greenhouse Big Tech",    _fetch_greenhouse_tier1),
        ("Greenhouse SaaS",        _fetch_greenhouse_saas),
        ("Greenhouse AI/Security", _fetch_greenhouse_ai_sec),

        # ── Lever API (major security vendors) ────────────────
        ("Lever Security",         _fetch_lever_security),

        # ── Community (confirmed working) ─────────────────────
        ("Hacker News Hiring",     _fetch_hackernews_hiring),
        ("InfoSec Jobs",           _fetch_infosec_jobs_board),
    ]

    for name, fn in fetchers:
        if time.time() - _start > BUDGET_SECONDS:
            log.warning(f"expanded_sources: 8-min budget exhausted at '{name}' — skipping rest.")
            break
        try:
            results = fn()
            all_jobs.extend(results)
            if results:
                log.info(f"✅ {name}: {len(results)} jobs")
        except Exception as e:
            log.warning(f"❌ expanded_sources: {name} failed: {e}")

    log.info(f"📊 Expanded Sources Total: {len(all_jobs)} jobs")
    return all_jobs
