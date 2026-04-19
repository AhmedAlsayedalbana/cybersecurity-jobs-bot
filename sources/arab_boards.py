"""
Arab Job Boards — v31
Scrapes Arabic-language job boards with large Egyptian/Gulf presence.

Sources:
  - Bayt.com       — largest Arab job board (RSS + search)
  - ArabiaJob      — Egyptian + Gulf jobs
  - Tanqeeb        — Egypt/Gulf professional jobs
  - LinkedIn Egypt Wuzzuf mirror (Wuzzuf API sometimes uses LI data)
  - Akhtaboot       — Jordan/Egypt/Gulf
  - Drjobpro.com   — Arabic/Egyptian portal
  - EgyCareers      — Egypt-focused
"""

import logging
import re
import json
import time
import urllib.parse
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

_SEC_KW = [
    "cybersecurity", "cyber security", "security analyst", "soc analyst",
    "penetration", "information security", "network security", "security engineer",
    "grc", "dfir", "cloud security", "devsecops", "malware", "forensic",
    "security architect", "security manager", "cyber", "infosec",
    "أمن المعلومات", "أمن سيبراني", "اختبار اختراق", "محلل أمن",
]

def _is_sec(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in _SEC_KW)


def _fetch_bayt_rss():
    """Bayt.com RSS feeds — largest Arab job board."""
    jobs = []
    seen = set()
    feeds = [
        "https://www.bayt.com/en/egypt/jobs/rss/",
        "https://www.bayt.com/en/egypt/jobs/cybersecurity-jobs/rss/",
        "https://www.bayt.com/en/egypt/jobs/information-security-jobs/rss/",
        "https://www.bayt.com/en/saudi-arabia/jobs/cybersecurity-jobs/rss/",
        "https://www.bayt.com/en/uae/jobs/cybersecurity-jobs/rss/",
    ]
    for feed_url in feeds:
        xml = get_text(feed_url, headers=_H)
        if not xml:
            continue
        titles   = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', xml)
        links    = re.findall(r'<link>(https://www\.bayt\.com[^<]+)</link>', xml)
        companies = re.findall(r'<company><!\[CDATA\[(.*?)\]\]></company>', xml)
        locations = re.findall(r'<location><!\[CDATA\[(.*?)\]\]></location>', xml)
        for i, title in enumerate(titles[1:], 1):  # skip channel title
            title = title.strip()
            if not title or title in seen or not _is_sec(title):
                continue
            seen.add(title)
            jobs.append(Job(
                title=title,
                company=companies[i-1].strip() if i-1 < len(companies) else "Unknown",
                location=locations[i-1].strip() if i-1 < len(locations) else "Egypt",
                url=links[i].strip() if i < len(links) else feed_url,
                source="bayt",
                tags=["bayt", "arab-board"],
            ))
        time.sleep(0.5)
    log.info(f"Bayt RSS: {len(jobs)} jobs")
    return jobs


def _fetch_akhtaboot():
    """Akhtaboot.com — Egypt/Jordan/Gulf jobs portal."""
    jobs = []
    seen = set()
    searches = [
        ("cybersecurity", "Egypt"),
        ("information security", "Egypt"),
        ("soc analyst", "Egypt"),
        ("security engineer", "Egypt"),
        ("cybersecurity", "Saudi Arabia"),
        ("cybersecurity", "UAE"),
    ]
    for query, country in searches:
        url = (
            f"https://www.akhtaboot.com/en/jobs?q={urllib.parse.quote(query)}"
            f"&country={urllib.parse.quote(country)}"
        )
        html = get_text(url, headers=_H)
        if not html:
            continue
        # Extract JSON-LD job postings
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title = (item.get("title") or "").strip()
                    if not title or title in seen or not _is_sec(title):
                        continue
                    seen.add(title)
                    org = item.get("hiringOrganization") or {}
                    company = org.get("name", "Unknown") if isinstance(org, dict) else "Unknown"
                    jobs.append(Job(
                        title=title, company=company,
                        location=country,
                        url=item.get("url", url),
                        source="akhtaboot",
                        tags=["akhtaboot", country.lower()],
                    ))
            except Exception:
                continue
        # Fallback: HTML title extraction
        raw_titles = re.findall(r'class="[^"]*job[_-]?title[^"]*"[^>]*>([^<]+)', html, re.IGNORECASE)
        for title in raw_titles:
            title = title.strip()
            if title and title not in seen and _is_sec(title):
                seen.add(title)
                jobs.append(Job(
                    title=title, company="Unknown",
                    location=country,
                    url=url,
                    source="akhtaboot",
                    tags=["akhtaboot"],
                ))
        time.sleep(0.8)
    log.info(f"Akhtaboot: {len(jobs)} jobs")
    return jobs


def _fetch_tanqeeb():
    """Tanqeeb.com — professional jobs Egypt + Gulf."""
    jobs = []
    seen = set()
    queries = [
        ("cybersecurity", "EG"),
        ("information security", "EG"),
        ("SOC analyst", "EG"),
        ("security engineer", "SA"),
        ("cybersecurity", "AE"),
    ]
    for kw, country in queries:
        url = f"https://tanqeeb.com/jobs?keyword={urllib.parse.quote(kw)}&country={country}"
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data = json.loads(block.strip())
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict) and data.get("@type") == "JobPosting":
                    items = [data]
                else:
                    continue
                for item in items:
                    title = (item.get("title") or "").strip()
                    if not title or title in seen or not _is_sec(title):
                        continue
                    seen.add(title)
                    org = item.get("hiringOrganization") or {}
                    company = org.get("name", "Unknown") if isinstance(org, dict) else "Unknown"
                    jobs.append(Job(
                        title=title, company=company,
                        location="Egypt" if country == "EG" else ("Saudi Arabia" if country == "SA" else "UAE"),
                        url=item.get("url", url),
                        source="tanqeeb",
                        tags=["tanqeeb"],
                    ))
            except Exception:
                continue
        time.sleep(0.8)
    log.info(f"Tanqeeb: {len(jobs)} jobs")
    return jobs


def _fetch_drjobpro():
    """Drjobpro.com — Arabic jobs portal for Egypt/Gulf."""
    jobs = []
    seen = set()
    queries = ["cybersecurity", "information security", "SOC analyst", "security engineer", "GRC"]
    for q in queries:
        url = f"https://www.drjobpro.com/jobs-search/?q={urllib.parse.quote(q)}&country=egypt"
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title = (item.get("title") or "").strip()
                    if not title or title in seen or not _is_sec(title):
                        continue
                    seen.add(title)
                    hiring = item.get("hiringOrganization", {})
                    company = hiring.get("name", "Unknown") if isinstance(hiring, dict) else "Unknown"
                    jobs.append(Job(
                        title=title, company=company, location="Egypt",
                        url=item.get("url", url),
                        source="drjobpro",
                        tags=["drjobpro", "egypt"],
                    ))
            except Exception:
                continue
        time.sleep(0.5)
    log.info(f"DrJobPro: {len(jobs)} jobs")
    return jobs


def fetch_arab_boards():
    """Aggregate all Arab job board sources."""
    all_jobs = []
    for fn in [_fetch_bayt_rss, _fetch_akhtaboot, _fetch_tanqeeb, _fetch_drjobpro]:
        try:
            all_jobs.extend(fn())
        except Exception as e:
            log.warning(f"arab_boards sub-fetcher {fn.__name__} failed: {e}")
    log.info(f"Arab Boards total: {len(all_jobs)} jobs")
    return all_jobs
