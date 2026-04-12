"""
Alternative job sources for Egypt cybersecurity jobs.

Replaces / supplements LinkedIn when it rate-limits.
Sources (all free, no API key needed):
  - Wuzzuf RSS          — Egypt's #1 job board, has a proper RSS feed
  - Forasna             — Arabic job board with RSS
  - Tanqeeb Egypt       — Arabic regional board
  - Indeed Egypt RSS    — Indeed's public RSS (no login needed)
  - CareerJet Egypt     — Has RSS by keyword+country

All return Job objects compatible with the rest of the pipeline.
"""

import logging
import re
import xml.etree.ElementTree as ET
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}

# Security keywords (Arabic + English)
SEC_KEYWORDS_EN = [
    "cybersecurity", "security analyst", "SOC analyst",
    "penetration", "information security", "network security",
    "security engineer", "GRC", "DFIR", "cloud security",
    "devsecops", "security", "cyber",
]

SEC_KEYWORDS_AR = [
    "أمن المعلومات", "أمن سيبراني", "محلل أمني",
    "مهندس أمن", "اختبار اختراق", "أمن الشبكات",
]


def _is_security_related(text: str) -> bool:
    text_lower = text.lower()
    for kw in SEC_KEYWORDS_EN:
        if kw.lower() in text_lower:
            return True
    for kw in SEC_KEYWORDS_AR:
        if kw in text:
            return True
    return False


def _parse_rss_jobs(xml_text: str, source_name: str, source_key: str,
                    default_location: str = "Egypt") -> list[Job]:
    """Parse a standard RSS feed into Job objects."""
    jobs = []
    if not xml_text:
        return jobs
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log.warning(f"{source_name}: XML parse error — {e}")
        return jobs

    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        link  = item.findtext("link",  "").strip()
        desc  = item.findtext("description", "") or ""

        if not title or not link:
            continue

        combined = title + " " + re.sub(r"<[^>]+>", " ", desc)
        if not _is_security_related(combined):
            continue

        # Try to extract location from description
        location = default_location
        for pat in [
            r"Location[:\s]+([^\n<|,]+)",
            r"City[:\s]+([^\n<|,]+)",
            r"القاهرة|الإسكندرية|الجيزة|مصر",
            r"Cairo|Alexandria|Giza|Egypt",
        ]:
            m = re.search(pat, combined, re.IGNORECASE)
            if m:
                try:
                    location = m.group(1).strip()[:80]
                except IndexError:
                    location = m.group(0).strip()[:80]
                break

        company_elem = item.find("author")
        company = company_elem.text.strip() if company_elem is not None and company_elem.text else source_name

        is_remote = "remote" in combined.lower() or "عن بعد" in combined

        jobs.append(Job(
            title=title,
            company=company,
            location=location,
            url=link,
            source=source_key,
            tags=[source_name, "egypt"],
            is_remote=is_remote,
        ))

    return jobs


# ── Wuzzuf ─────────────────────────────────────────────────────
# Wuzzuf has proper RSS endpoints — much more stable than scraping LinkedIn

WUZZUF_SEARCHES = [
    "cybersecurity",
    "information+security",
    "SOC+analyst",
    "security+engineer",
    "penetration+tester",
    "network+security",
    "GRC+analyst",
    "cloud+security",
    "devsecops",
    "security+analyst",
]

def _fetch_wuzzuf() -> list[Job]:
    """
    Fetch from Wuzzuf's search RSS.
    Correct URL: https://wuzzuf.net/search/jobs/rss/?q=KEYWORD&a=hpb
    """
    jobs = []
    seen_urls: set[str] = set()

    for kw in WUZZUF_SEARCHES:
        url = f"https://wuzzuf.net/search/jobs/rss/?q={kw.replace(' ', '+')}&a=hpb"
        xml = get_text(url, headers=_HEADERS)
        if not xml:
            continue

        for job in _parse_rss_jobs(xml, "Wuzzuf", "wuzzuf", "Egypt"):
            if job.url not in seen_urls:
                seen_urls.add(job.url)
                jobs.append(job)

    log.info(f"Wuzzuf: {len(jobs)} security jobs")
    return jobs


# ── Indeed Egypt RSS ───────────────────────────────────────────
# Indeed exposes public RSS for job searches — no login needed

INDEED_SEARCHES = [
    ("cybersecurity", "egypt"),
    ("information security", "egypt"),
    ("SOC analyst", "egypt"),
    ("security engineer", "egypt"),
    ("penetration tester", "egypt"),
    ("network security", "egypt"),
]

def _fetch_indeed_egypt() -> list[Job]:
    """
    Fetch from Indeed Egypt RSS.
    URL: https://eg.indeed.com/rss?q=KEYWORD&l=LOCATION&sort=date
    """
    jobs = []
    seen_urls: set[str] = set()

    for query, location in INDEED_SEARCHES:
        q = query.replace(" ", "+")
        l = location.replace(" ", "+")
        url = f"https://eg.indeed.com/rss?q={q}&l={l}&sort=date"
        xml = get_text(url, headers=_HEADERS)
        if not xml:
            # Fallback: try the global indeed with Egypt location
            url = f"https://www.indeed.com/rss?q={q}&l={l}&sort=date"
            xml = get_text(url, headers=_HEADERS)
        if not xml:
            continue

        for job in _parse_rss_jobs(xml, "Indeed Egypt", "indeed_eg", "Egypt"):
            if job.url not in seen_urls:
                seen_urls.add(job.url)
                jobs.append(job)

    log.info(f"Indeed Egypt: {len(jobs)} security jobs")
    return jobs


# ── CareerJet Egypt ────────────────────────────────────────────
# CareerJet has a free API / RSS by keyword + country

CAREERJET_SEARCHES = [
    "cybersecurity",
    "information security",
    "SOC analyst",
    "security engineer",
    "penetration testing",
]

def _fetch_careerjet_egypt() -> list[Job]:
    """Fetch from CareerJet Egypt RSS."""
    jobs = []
    seen_urls: set[str] = set()

    for kw in CAREERJET_SEARCHES:
        q = kw.replace(" ", "+")
        url = f"https://www.careerjet.com.eg/jobs/rss?s={q}&l=Egypt"
        xml = get_text(url, headers=_HEADERS)
        if not xml:
            continue

        for job in _parse_rss_jobs(xml, "CareerJet Egypt", "careerjet_eg", "Egypt"):
            if job.url not in seen_urls:
                seen_urls.add(job.url)
                jobs.append(job)

    log.info(f"CareerJet Egypt: {len(jobs)} security jobs")
    return jobs


# ── Forasna ────────────────────────────────────────────────────
# Arabic job board targeting Egypt & MENA

def _fetch_forasna() -> list[Job]:
    """Fetch from Forasna RSS (Arabic job board for Egypt)."""
    jobs = []

    # Forasna RSS by category (IT/Tech category)
    urls = [
        "https://www.forasna.com/feed/",
        "https://www.forasna.com/jobs/technology/feed/",
    ]

    for url in urls:
        xml = get_text(url, headers=_HEADERS)
        if not xml:
            continue
        for job in _parse_rss_jobs(xml, "Forasna", "forasna", "Egypt"):
            jobs.append(job)

    log.info(f"Forasna: {len(jobs)} security jobs")
    return jobs


# ── Tanqeeb ────────────────────────────────────────────────────
# Pan-Arab job board with Egypt listings

def _fetch_tanqeeb_egypt() -> list[Job]:
    """Fetch from Tanqeeb Egypt cybersecurity listings using correct URL format."""
    import json
    jobs = []
    seen_urls: set[str] = set()

    searches = [
        "cybersecurity",
        "information-security",
        "security-analyst",
        "security-engineer",
    ]

    for kw in searches:
        url = f"https://www.tanqeeb.com/{kw}-jobs-in-egypt"
        html = get_text(url, headers=_HEADERS)
        if not html:
            continue

        # Extract JSON-LD job postings
        for block in re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title = item.get("title", "").strip()
                    link = item.get("url", url)
                    if not title or link in seen_urls:
                        continue
                    seen_urls.add(link)
                    org = item.get("hiringOrganization", {})
                    company = org.get("name", "").strip() if isinstance(org, dict) else "Tanqeeb Employer"
                    jobs.append(Job(
                        title=title, company=company or "Tanqeeb Employer",
                        location="Egypt", url=link,
                        source="tanqeeb", tags=["tanqeeb", "egypt"],
                        is_remote=False,
                    ))
            except (json.JSONDecodeError, KeyError):
                continue

    log.info(f"Tanqeeb Egypt: {len(jobs)} security jobs")
    return jobs


# ── Public entry point ─────────────────────────────────────────

def fetch_egypt_alt() -> list[Job]:
    """
    Fetch Egypt cybersecurity jobs from alternative sources
    (Wuzzuf, Indeed, CareerJet, Forasna, Tanqeeb).

    These are rate-limit-free alternatives to LinkedIn for Egyptian jobs.
    """
    all_jobs: list[Job] = []
    seen_urls: set[str] = set()

    fetchers = [
        ("Wuzzuf",         _fetch_wuzzuf),
        ("Indeed Egypt",   _fetch_indeed_egypt),
        ("CareerJet EG",   _fetch_careerjet_egypt),
        ("Forasna",        _fetch_forasna),
        ("Tanqeeb EG",     _fetch_tanqeeb_egypt),
    ]

    for name, fn in fetchers:
        try:
            jobs = fn()
            for job in jobs:
                if job.url not in seen_urls:
                    seen_urls.add(job.url)
                    all_jobs.append(job)
        except Exception as e:
            log.warning(f"Egypt Alt ({name}): unexpected error — {e}")

    log.info(f"Egypt Alt (total): {len(all_jobs)} jobs across all sources")
    return all_jobs
