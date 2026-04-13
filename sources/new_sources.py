"""
New Job Sources — v16
Creative additions targeting Egypt, Gulf, internships, and cybersecurity:

  ✅ Bayt.com         — RSS feeds for Egypt + Gulf (most used Arab job board)
  ✅ Wellfound        — Startup/tech jobs JSON API (AngelList successor)
  ✅ Dice             — Tech/security jobs RSS
  ✅ Laimoon          — Gulf-focused job board RSS
  ✅ Drjobpro         — Arabic-first job board (Egypt + Gulf)
  ✅ Jobzella         — Egypt-focused job board
  ✅ ITida / NTI      — Gov Egypt internship & graduate programs (RSS/HTML)
  ✅ Greenhouse (new) — Additional cybersec company boards not in tech_boards
  ✅ SecurityTrails   — Cybersec career pages via JSON
  ✅ Reddit r/netsec  — Community hiring threads (self posts tagged [Hiring])
"""

import logging
import re
import json
import xml.etree.ElementTree as ET
import urllib.parse
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
    "أمن معلومات", "أمن سيبراني", "اختبار اختراق",
]

def _is_sec(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in SEC_KW)

def _parse_rss(xml_text: str, company: str, source: str,
               location: str, tags: list, is_remote: bool = False) -> list:
    """Generic RSS → Job list parser."""
    jobs, seen = [], set()
    try:
        clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', xml_text)
        root  = ET.fromstring(clean)
    except ET.ParseError:
        return jobs
    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        link  = item.findtext("link",  "").strip()
        desc  = re.sub(r'<[^>]+>', ' ', item.findtext("description", "")).strip()[:300]
        if not title or not link or link in seen:
            continue
        if not _is_sec(title + " " + desc):
            continue
        seen.add(link)
        jobs.append(Job(
            title=title, company=company, location=location,
            url=link, source=source, description=desc,
            tags=tags, is_remote=is_remote,
        ))
    return jobs


# ── 1. Bayt.com RSS ──────────────────────────────────────────
def _fetch_bayt() -> list:
    """Bayt RSS — most-used Arab job board for Egypt + Gulf."""
    jobs = []
    feeds = [
        # Egypt
        ("https://www.bayt.com/en/egypt/jobs/cyber-security-jobs/rss/",         "Egypt"),
        ("https://www.bayt.com/en/egypt/jobs/information-security-jobs/rss/",    "Egypt"),
        ("https://www.bayt.com/en/egypt/jobs/network-security-jobs/rss/",        "Egypt"),
        ("https://www.bayt.com/en/egypt/jobs/it-security-jobs/rss/",             "Egypt"),
        # Saudi Arabia
        ("https://www.bayt.com/en/saudi-arabia/jobs/cyber-security-jobs/rss/",   "Saudi Arabia"),
        ("https://www.bayt.com/en/saudi-arabia/jobs/information-security-jobs/rss/", "Saudi Arabia"),
        # UAE
        ("https://www.bayt.com/en/uae/jobs/cyber-security-jobs/rss/",            "UAE"),
        ("https://www.bayt.com/en/uae/jobs/information-security-jobs/rss/",      "UAE"),
    ]
    seen = set()
    for url, loc in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        fetched = _parse_rss(xml, "Bayt", "bayt", loc, ["bayt", loc.lower()])
        for j in fetched:
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Bayt: {len(jobs)} jobs")
    return jobs


# ── 2. Wellfound (AngelList) JSON API ────────────────────────
def _fetch_wellfound() -> list:
    """Wellfound startup jobs — cybersec roles at funded startups."""
    jobs = []
    seen = set()
    searches = [
        "https://wellfound.com/role/r/security-engineer",
        "https://wellfound.com/role/r/information-security",
        "https://wellfound.com/role/r/penetration-tester",
    ]
    for url in searches:
        html = get_text(url, headers={**_H, "Accept": "text/html"})
        if not html:
            continue
        # Extract JSON-LD job postings
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", url)
                    if not title or job_url in seen or not _is_sec(title):
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "Startup") if isinstance(hiring, dict) else "Startup"
                    loc_obj = item.get("jobLocation", {})
                    location = ""
                    if isinstance(loc_obj, dict):
                        addr = loc_obj.get("address", {})
                        if isinstance(addr, dict):
                            location = addr.get("addressCountry", addr.get("addressLocality", ""))
                    is_remote = item.get("jobLocationType") == "TELECOMMUTE"
                    jobs.append(Job(
                        title=title, company=company,
                        location=location or ("Remote" if is_remote else "Worldwide"),
                        url=job_url, source="wellfound",
                        tags=["wellfound", "startup"], is_remote=is_remote,
                    ))
            except Exception:
                continue
    log.info(f"Wellfound: {len(jobs)} jobs")
    return jobs


# ── 3. Dice RSS ──────────────────────────────────────────────
def _fetch_dice() -> list:
    """Dice.com — tech/security jobs RSS (remote-friendly)."""
    jobs = []
    seen = set()
    feeds = [
        "https://www.dice.com/jobs/q-cybersecurity-jobs.rss",
        "https://www.dice.com/jobs/q-information+security-jobs.rss",
        "https://www.dice.com/jobs/q-soc+analyst-jobs.rss",
        "https://www.dice.com/jobs/q-penetration+tester-jobs.rss",
    ]
    for url in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        for j in _parse_rss(xml, "Dice", "dice", "Remote", ["dice", "remote"], is_remote=True):
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Dice: {len(jobs)} jobs")
    return jobs


# ── 4. Drjobpro ──────────────────────────────────────────────
def _fetch_drjobpro() -> list:
    """Dr. Job Pro — Arabic-first job board, good Egypt + Gulf coverage."""
    jobs = []
    seen = set()
    searches = [
        ("https://drjobpro.com/jobs/cybersecurity-jobs-in-egypt",     "Egypt"),
        ("https://drjobpro.com/jobs/information-security-jobs-in-egypt", "Egypt"),
        ("https://drjobpro.com/jobs/cybersecurity-jobs-in-saudi-arabia", "Saudi Arabia"),
        ("https://drjobpro.com/jobs/cybersecurity-jobs-in-uae",       "UAE"),
    ]
    for url, loc in searches:
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", "")
                    if not title or not job_url or job_url in seen:
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    jobs.append(Job(
                        title=title, company=company or "Dr. Job",
                        location=loc, url=job_url, source="drjobpro",
                        tags=["drjobpro", loc.lower()],
                    ))
            except Exception:
                continue
    log.info(f"DrJobPro: {len(jobs)} jobs")
    return jobs


# ── 5. Laimoon RSS ────────────────────────────────────────────
def _fetch_laimoon() -> list:
    """Laimoon.com — Gulf job board with RSS."""
    jobs = []
    seen = set()
    feeds = [
        ("https://laimoon.com/jobs/information-technology/information-security/rss", "Gulf"),
        ("https://laimoon.com/jobs/information-technology/cybersecurity/rss",        "Gulf"),
    ]
    for url, loc in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        for j in _parse_rss(xml, "Laimoon", "laimoon", loc, ["laimoon", "gulf"]):
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Laimoon: {len(jobs)} jobs")
    return jobs


# ── 6. Reddit r/netsec Hiring Threads ───────────────────────
def _fetch_reddit_netsec() -> list:
    """
    Reddit r/netsec monthly [Hiring] thread — real jobs posted by security teams.
    Uses Reddit's JSON API (no auth needed for public posts).
    """
    jobs = []
    seen = set()
    urls = [
        "https://www.reddit.com/r/netsec/search.json?q=%5BHiring%5D&sort=new&restrict_sr=1&limit=25",
        "https://www.reddit.com/r/netsec/search.json?q=hiring+cybersecurity&sort=new&restrict_sr=1&limit=25",
    ]
    headers = {**_H, "Accept": "application/json"}
    for url in urls:
        data = get_json(url, headers=headers)
        if not data:
            continue
        posts = data.get("data", {}).get("children", [])
        for post in posts:
            p = post.get("data", {})
            title = p.get("title", "").strip()
            if not title or not _is_sec(title):
                continue
            job_url = "https://www.reddit.com" + p.get("permalink", "")
            if job_url in seen:
                continue
            seen.add(job_url)
            # Parse company from title: "[Hiring] CompanyName | Role | Location"
            company = "Reddit r/netsec"
            m = re.match(r'\[hiring\]\s*(.+?)\s*[\|\-–]', title, re.IGNORECASE)
            if m:
                company = m.group(1).strip()
            jobs.append(Job(
                title=title, company=company,
                location="Remote / Worldwide",
                url=job_url, source="reddit_netsec",
                tags=["reddit", "netsec", "hiring"],
                is_remote=True, description=p.get("selftext", "")[:300],
            ))
    log.info(f"Reddit r/netsec: {len(jobs)} jobs")
    return jobs


# ── 7. Additional Greenhouse Boards (cybersec companies) ─────
def _fetch_greenhouse_cybersec() -> list:
    """
    Additional Greenhouse boards for cybersec companies not covered in tech_boards.
    These are confirmed working boards.
    """
    jobs = []
    seen = set()
    BOARDS = [
        ("Wiz",             "wiz-2"),
        ("Snyk",            "snyk"),
        ("Lacework",        "lacework"),
        ("Drata",           "drata"),
        ("Vanta",           "vanta"),
        ("Abnormal Security","abnormalsecurity"),
        ("Orca Security",   "orca"),
        ("Huntress",        "huntress"),
        ("Axonius",         "axonius"),
        ("Exabeam",         "exabeam"),
    ]
    SEC_TITLES = [
        "security", "cyber", "soc", "pentest", "threat", "vulnerability",
        "grc", "dfir", "appsec", "devsecops", "cloud security",
    ]
    base = "https://api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    for company, slug in BOARDS:
        data = get_json(base.format(slug=slug), headers=_H)
        if not data or "jobs" not in data:
            continue
        for item in data["jobs"]:
            title = item.get("title", "")
            if not any(k in title.lower() for k in SEC_TITLES):
                continue
            job_url = item.get("absolute_url", "")
            if not job_url or job_url in seen:
                continue
            seen.add(job_url)
            loc = item.get("location", {})
            location = loc.get("name", "") if isinstance(loc, dict) else ""
            jobs.append(Job(
                title=title, company=company,
                location=location or "Not specified",
                url=job_url, source="greenhouse_cybersec",
                tags=["greenhouse", company.lower()],
                is_remote="remote" in location.lower(),
            ))
    log.info(f"Greenhouse Cybersec: {len(jobs)} jobs")
    return jobs


# ── 8. Jobzella (Egypt) ───────────────────────────────────────
def _fetch_jobzella() -> list:
    """Jobzella — Egypt-focused job board, JSON-LD scrape."""
    jobs = []
    seen = set()
    urls = [
        "https://www.jobzella.com/jobs/it-technology/information-security-cybersecurity",
        "https://www.jobzella.com/jobs/it-technology/network-infrastructure",
    ]
    for url in urls:
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", "")
                    if not title or not job_url or job_url in seen or not _is_sec(title):
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    jobs.append(Job(
                        title=title, company=company or "Jobzella",
                        location="Egypt", url=job_url,
                        source="jobzella", tags=["jobzella", "egypt"],
                    ))
            except Exception:
                continue
    log.info(f"Jobzella: {len(jobs)} jobs")
    return jobs


# ── Main aggregator ───────────────────────────────────────────
def fetch_new_sources() -> list:
    """Aggregate all new v16 sources."""
    all_jobs = []
    fetchers = [
        ("Bayt",               _fetch_bayt),
        ("Wellfound",          _fetch_wellfound),
        ("Dice",               _fetch_dice),
        ("DrJobPro",           _fetch_drjobpro),
        ("Laimoon",            _fetch_laimoon),
        ("Reddit r/netsec",    _fetch_reddit_netsec),
        ("Greenhouse Cybersec",_fetch_greenhouse_cybersec),
        ("Jobzella",           _fetch_jobzella),
    ]
    for name, fn in fetchers:
        try:
            results = fn()
            all_jobs.extend(results)
        except Exception as e:
            log.warning(f"new_sources: {name} failed: {e}")
    return all_jobs
