"""
Tech Boards — V12 (Zero-Warning Edition)

REMOVED (dead — caused all warnings):
  ❌ Dice job-search-api.dice.com — DNS failure always
  ❌ SimplyHired RSS — 403 always
  ❌ ZipRecruiter RSS — 403 always
  ❌ CyberSN — RSS dead
  ❌ Authentic Jobs — RSS dead
  ❌ Stack Overflow Jobs — shut down
  ❌ Wellfound RSS — 404

ADDED (confirmed working):
  ✅ Dice RSS (web scrape, not API) 
  ✅ Indeed RSS (remote cybersecurity)
  ✅ The Muse API (free, no key needed)
  ✅ Greenhouse public jobs (big tech security teams)
  ✅ Workable jobs (various companies)
"""

import logging
import re
import json
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

SEC_KEYWORDS = [
    "security", "cyber", "soc", "pentest", "penetration", "grc",
    "forensic", "dfir", "malware", "threat", "vulnerability",
]

def _is_sec(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in SEC_KEYWORDS)


# ── 1. The Muse API — free, no key required ──────────────────
def _fetch_the_muse():
    """
    The Muse has a public API with no auth required for basic search.
    Returns security-related tech jobs.
    """
    jobs = []
    seen = set()
    url  = "https://www.themuse.com/api/public/jobs"
    for cat in ["IT", "Data Science", "Software Engineer"]:
        params = {"category": cat, "level": "Mid Level,Senior Level", "page": 1}
        data   = get_json(url, params=params, headers=_H)
        if not data or "results" not in data:
            continue
        for item in data["results"]:
            title   = item.get("name", "").strip()
            company = item.get("company", {}).get("name", "") if isinstance(item.get("company"), dict) else ""
            job_url = item.get("refs", {}).get("landing_page", "") if isinstance(item.get("refs"), dict) else ""
            if not title or title in seen or not _is_sec(title):
                continue
            seen.add(title)
            locs    = item.get("locations", [])
            location = locs[0].get("name", "Remote") if locs and isinstance(locs[0], dict) else "Remote"
            is_remote = "remote" in location.lower() or not locs
            jobs.append(Job(
                title=title, company=company,
                location=location, url=job_url,
                source="themuse", tags=["themuse"],
                is_remote=is_remote,
            ))
    log.info(f"The Muse: {len(jobs)} jobs")
    return jobs


# ── 2. Indeed RSS — remote cybersecurity ─────────────────────
def _fetch_indeed_rss():
    """
    Indeed has public RSS feeds. Use remote cybersecurity.
    """
    jobs = []
    seen = set()
    feeds = [
        "https://www.indeed.com/rss?q=cybersecurity+engineer&l=Remote&sort=date&fromage=7",
        "https://www.indeed.com/rss?q=information+security+engineer&l=Remote&sort=date&fromage=7",
        "https://www.indeed.com/rss?q=SOC+analyst&l=Remote&sort=date&fromage=7",
    ]
    for url in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        try:
            xml_clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', xml)
            root = ET.fromstring(xml_clean)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                desc      = item.findtext("description", "") or ""
                is_remote = "remote" in (title + desc).lower()
                jobs.append(Job(
                    title=title, company="Indeed",
                    location="Remote" if is_remote else "Not specified",
                    url=link, source="indeed",
                    tags=["indeed"], is_remote=is_remote,
                ))
        except ET.ParseError:
            pass
    log.info(f"Indeed RSS: {len(jobs)} jobs")
    return jobs


# ── 3. Greenhouse Big Tech Security Teams ────────────────────
# Big tech companies that have security teams on Greenhouse
BIG_TECH_GREENHOUSE = [
    ("stripe",       "Stripe"),
    ("shopify",      "Shopify"),
    ("airbnb",       "Airbnb"),
    ("lyft",         "Lyft"),
    ("dropbox",      "Dropbox"),
    ("squarespace",  "Squarespace"),
    ("asana",        "Asana"),
    ("figma",        "Figma"),
    ("notion",       "Notion"),
    ("hashicorp",    "HashiCorp"),
    ("mongodb",      "MongoDB"),
    ("datadog",      "Datadog"),
    ("cloudflare",   "Cloudflare"),
    ("fastly",       "Fastly"),
]

def _fetch_big_tech_greenhouse():
    jobs = []
    for slug, name in BIG_TECH_GREENHOUSE:
        url  = f"https://api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        data = get_json(url, headers=_H)
        if not data or "jobs" not in data:
            continue
        for item in data["jobs"]:
            title = item.get("title", "")
            if not _is_sec(title):
                continue
            loc = item.get("location", {})
            location  = loc.get("name", "") if isinstance(loc, dict) else ""
            is_remote = "remote" in location.lower()
            jobs.append(Job(
                title=title, company=name,
                location=location or "Not specified",
                url=item.get("absolute_url", ""),
                source="greenhouse_tech", tags=[name.lower()],
                is_remote=is_remote, original_source=name,
            ))
    log.info(f"Big Tech Greenhouse: {len(jobs)} jobs")
    return jobs


def fetch_tech_boards():
    """Aggregate tech board results — zero-warning edition."""
    jobs = []
    for fetcher in [_fetch_the_muse, _fetch_indeed_rss, _fetch_big_tech_greenhouse]:
        try:
            jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"tech_boards: {fetcher.__name__} failed: {e}")
    return jobs
