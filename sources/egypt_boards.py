"""
sources/egypt_boards.py — v1.0
Egyptian & Arab job boards with cybersecurity focus.

SOURCES:
  • Wazzif (وظف) — Egyptian job board (wazzif.com)
  • Akhtaboot — MENA regional board (Egypt/Gulf)
  • Forasna — Egyptian jobs (forasna.com)
  • Drjobpro — Egypt/Gulf jobs
  • JobLine Egypt — Egyptian board
  • Careers Egypt — careers.eg

All sources have security-keyword filtering and geo-tagging.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

from models import Job
from sources.marketplace_sources import SourceResult

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_SEC_TERMS = [
    "cybersecurity", "cyber security", "information security", "infosec",
    "security analyst", "security engineer", "soc analyst", "soc engineer",
    "grc", "penetration", "pentest", "appsec", "application security",
    "cloud security", "network security", "threat", "dfir", "iam",
    "incident response", "malware", "vulnerability", "devsecops",
    "privacy", "data protection", "ciso", "compliance analyst",
    "أمن", "أمن سيبراني", "أمن معلومات", "اختراق", "حماية",
]


def _is_sec(text: str) -> bool:
    t = (text or "").lower()
    return any(term in t for term in _SEC_TERMS)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _make_job(
    title: str, company: str, location: str, url: str,
    source: str, description: str = "", priority: int = 25,
    *, posted_date: datetime | None = None, job_id: str = "",
) -> Job | None:
    title = _clean(title)
    url = (url or "").strip()
    if not title or not url:
        return None
    return Job(
        title=title,
        company=_clean(company) or "Employer",
        location=_clean(location) or "Egypt",
        url=url,
        source=source,
        source_key=source,
        description=_clean(description)[:500],
        posted_date=posted_date or datetime.utcnow(),
        geo_hint="egypt",
        origin_priority=priority,
        tags=[source, "egypt", "egypt_board", *([f"job_id:{job_id}"] if job_id else [])],
        content_type="job_listing",
    )


# ── 1. Wazzif (وظف) ──────────────────────────────────────────────────────────
def _wazzif_posted_date(value: object) -> datetime | None:
    text = _clean(str(value or ""))
    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})(?:[T\s]([0-2]\d:[0-5]\d(?::[0-5]\d)?))?", text)
    if match:
        try:
            return datetime.fromisoformat(" ".join(part for part in match.groups() if part))
        except ValueError:
            pass
    relative = re.search(r"\b(\d{1,3})\s*(minute|minutes|min|hour|hours|day|days|week|weeks)\s+ago\b", text, re.I)
    if relative:
        amount, unit = int(relative.group(1)), relative.group(2).lower()
        hours = amount / 60 if unit.startswith("min") else amount if unit.startswith("hour") else amount * 24 if unit.startswith("day") else amount * 24 * 7
        return datetime.utcnow() - timedelta(hours=hours)
    arabic = re.search(r"منذ\s*(\d{1,3})?\s*(دقيقة|دقائق|ساعة|ساعات|يوم|أيام|اسبوع|أسبوع|أسابيع)", text)
    if arabic:
        amount, unit = int(arabic.group(1) or 1), arabic.group(2)
        hours = amount / 60 if "دقيق" in unit else amount if "ساع" in unit else amount * 24 if "يوم" in unit else amount * 24 * 7
        return datetime.utcnow() - timedelta(hours=hours)
    return None


def _wazzif_blocked_page(html: str) -> bool:
    lowered = (html or "").lower()
    return any(marker in lowered for marker in (
        "just a moment", "performing security verification", "captcha", "cf-chl-",
        "403 forbidden", "access denied", "parked domain", "godaddy",
        "window.location.href=\"/lander", "window.location.href='/lander",
    ))


def _wazzif_flatten(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _wazzif_flatten(child)
    elif isinstance(value, list):
        for child in value:
            yield from _wazzif_flatten(child)


def _wazzif_text(record: dict, *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("title") or value.get("label") or value.get("address")
        if isinstance(value, list):
            value = ", ".join(_clean(str(item.get("name") if isinstance(item, dict) else item)) for item in value)
        cleaned = _clean(str(value or ""))
        if cleaned:
            return cleaned
    return ""


def _wazzif_structured_jobs(html: str, seen: set[str]) -> tuple[list[Job], int, int]:
    """Parse JSON-LD and Next.js cards without inventing a posted timestamp."""
    jobs: list[Job] = []
    recognizable = 0
    incomplete_security = 0
    blobs = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I)
    next_data = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.S | re.I)
    if next_data:
        blobs.append(next_data.group(1))
    for blob in blobs:
        try:
            data = json.loads(blob.strip())
        except (TypeError, ValueError):
            continue
        for item in _wazzif_flatten(data):
            title = _wazzif_text(item, "title", "name", "jobTitle", "headline")
            link = _wazzif_text(item, "url", "link", "jobUrl", "job_url", "detailUrl", "detail_url", "canonicalUrl")
            if not title or not link:
                continue
            full_url = urllib.parse.urljoin("https://wazzif.com", link)
            if urllib.parse.urlparse(full_url).netloc.lower().removeprefix("www.") != "wazzif.com":
                continue
            recognizable += 1
            description = _wazzif_text(item, "description", "summary", "snippet", "shortDescription")
            if not _is_sec(f"{title} {description}"):
                continue
            posted = _wazzif_posted_date(_wazzif_text(item, "datePosted", "publishedAt", "createdAt", "postedAt", "posted_at", "date"))
            if not posted:
                incomplete_security += 1
                continue
            if full_url in seen:
                continue
            seen.add(full_url)
            organization = item.get("hiringOrganization")
            company = _wazzif_text(item, "company", "companyName", "employer", "employerName")
            if not company and isinstance(organization, dict):
                company = _clean(str(organization.get("name", "")))
            location = _wazzif_text(item, "location", "locationName", "city", "cityName", "jobLocation", "address")
            job_id = _wazzif_text(item, "jobId", "job_id", "id", "uid")
            job = _make_job(
                title=title, company=company or "Wazzif Employer", location=location or "Egypt",
                url=full_url, source="wazzif", description=description, priority=23,
                posted_date=posted, job_id=job_id,
            )
            if job:
                jobs.append(job)
    return jobs, recognizable, incomplete_security


def fetch_wazzif() -> list[Job] | SourceResult:
    """Fetch public Wazzif listings and distinguish a block from parser drift."""
    jobs: list[Job] = []
    seen: set[str] = set()
    successful_pages = 0
    blocked_pages = 0
    recognizable_records = 0
    incomplete_security_records = 0
    attempted_urls: list[str] = []
    queries = [
        "cybersecurity", "security analyst", "information security",
        "penetration testing", "SOC analyst", "GRC", "network security",
        "أمن معلومات", "أمن سيبراني",
    ]

    for q in queries:
        url = f"https://wazzif.com/jobs?q={urllib.parse.quote(q)}&country=egypt"
        attempted_urls.append(url)
        try:
            resp = requests.get(url, headers=_H, timeout=12)
            if resp.status_code != 200:
                continue
            html = resp.text
            successful_pages += 1
        except Exception as exc:
            log.debug("Wazzif search %s: %s", q, exc)
            continue
        if _wazzif_blocked_page(html):
            blocked_pages += 1
            continue

        structured_jobs, structured_recognizable, structured_incomplete = _wazzif_structured_jobs(html, seen)
        jobs.extend(structured_jobs)
        recognizable_records += structured_recognizable
        incomplete_security_records += structured_incomplete

        for match in re.finditer(
            r'<a[^>]+href=["\']([^"\']*/(?:jobs?|vacancy)/[^"\']+)["\'][^>]*>(.*?)</a>', html,
            re.IGNORECASE | re.DOTALL,
        ):
            href, title_raw = match.groups()
            context = html[max(0, match.start() - 280): match.end() + 520]
            title = _clean(title_raw)
            recognizable_records += 1
            if not title or not _is_sec(f"{title} {context}"):
                continue
            full_url = urllib.parse.urljoin("https://wazzif.com", href)
            if full_url in seen:
                continue
            posted = _wazzif_posted_date(context)
            if not posted:
                incomplete_security_records += 1
                continue
            seen.add(full_url)
            job = _make_job(
                title=title, company="Wazzif Employer", location="Egypt", url=full_url,
                source="wazzif", description=context, priority=23, posted_date=posted,
            )
            if job:
                jobs.append(job)
        time.sleep(0.4)

    log.info("Wazzif: %d jobs", len(jobs))
    if jobs:
        return SourceResult(jobs=jobs, status="success", transport="direct", attempted_urls=tuple(attempted_urls))
    if not successful_pages:
        return SourceResult(status="blocked", transport="direct", error_code="wazzif_unavailable", attempted_urls=tuple(attempted_urls))
    if blocked_pages == successful_pages:
        return SourceResult(status="blocked", transport="direct", error_code="wazzif_blocked", attempted_urls=tuple(attempted_urls))
    if incomplete_security_records:
        return SourceResult(status="parse_changed", transport="direct", error_code="wazzif_missing_posted_date", attempted_urls=tuple(attempted_urls))
    if recognizable_records:
        return SourceResult(status="empty", transport="direct", error_code="no_matching_security_listings", attempted_urls=tuple(attempted_urls))
    return SourceResult(status="parse_changed", transport="direct", error_code="wazzif_card_markup_unrecognized", attempted_urls=tuple(attempted_urls))


# ── 2. Akhtaboot (Egypt/MENA) ────────────────────────────────────────────────
def fetch_akhtaboot_egypt() -> list[Job]:
    """
    Akhtaboot.com — largest Arabic MENA job board (Egypt + Gulf).
    Uses JSON-LD and structured search results.
    """
    jobs: list[Job] = []
    seen: set[str] = set()

    queries = ["cybersecurity", "security analyst", "information security", "penetration testing"]
    base = "https://www.akhtaboot.com/en"

    for q in queries:
        url = f"{base}/jobs/search?q={urllib.parse.quote(q)}&l=Egypt"
        try:
            resp = requests.get(url, headers=_H, timeout=12)
            if resp.status_code not in (200, 301, 302):
                log.debug("Akhtaboot %s: HTTP %s", q, resp.status_code)
                continue
            html = resp.text
        except Exception as exc:
            log.debug("Akhtaboot %s: %s", q, exc)
            continue

        # JSON-LD extraction
        for blob in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.S | re.I
        ):
            try:
                data = json.loads(blob.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                        continue
                    link = item.get("url", "")
                    t = item.get("title", "")
                    if not link or link in seen or not _is_sec(t):
                        continue
                    seen.add(link)
                    org = item.get("hiringOrganization", {})
                    company = org.get("name", "Akhtaboot Employer") if isinstance(org, dict) else "Akhtaboot Employer"
                    job = _make_job(
                        title=t, company=company,
                        location="Egypt", url=link,
                        source="akhtaboot", priority=24,
                    )
                    if job:
                        jobs.append(job)
            except Exception:
                continue

        # Regex link extraction as fallback
        for href, anchor_text in re.findall(
            r'<a[^>]+href="(https?://[^"]*akhtaboot[^"]*)"[^>]*>(.*?)</a>',
            html, re.IGNORECASE | re.DOTALL
        ):
            title = _clean(anchor_text)
            if not title or not _is_sec(title) or href in seen:
                continue
            seen.add(href)
            job = _make_job(
                title=title, company="Akhtaboot Employer",
                location="Egypt", url=href,
                source="akhtaboot", priority=24,
            )
            if job:
                jobs.append(job)

        time.sleep(0.5)

    log.info("Akhtaboot Egypt: %d jobs", len(jobs))
    return jobs


# ── 3. DrJobPro (Egypt/Gulf) ─────────────────────────────────────────────────
def fetch_drjobpro_egypt() -> list[Job]:
    """
    DrJobPro.com — Egypt + Gulf focused job board.
    """
    jobs: list[Job] = []
    seen: set[str] = set()
    queries = ["cybersecurity", "information security", "security analyst", "network security"]

    for q in queries:
        url = f"https://www.drjobpro.com/en/jobs/list?q={urllib.parse.quote(q)}&country=egypt"
        try:
            resp = requests.get(url, headers=_H, timeout=12)
            if resp.status_code != 200:
                continue
            html = resp.text
        except Exception as exc:
            log.debug("DrJobPro %s: %s", q, exc)
            continue

        for blob in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.S | re.I
        ):
            try:
                data = json.loads(blob.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                        continue
                    link = item.get("url", "")
                    t = item.get("title", "")
                    if not link or link in seen or not _is_sec(t):
                        continue
                    seen.add(link)
                    org = item.get("hiringOrganization", {})
                    company = org.get("name", "DrJobPro Employer") if isinstance(org, dict) else "DrJobPro Employer"
                    job = _make_job(
                        title=t, company=company,
                        location="Egypt", url=link,
                        source="drjobpro", priority=25,
                    )
                    if job:
                        jobs.append(job)
            except Exception:
                continue

        time.sleep(0.4)

    log.info("DrJobPro Egypt: %d jobs", len(jobs))
    return jobs


# ── 4. Forasna (Egypt direct) ─────────────────────────────────────────────────
def fetch_forasna() -> list[Job]:
    """
    Forasna.com — Egypt direct employment board.
    """
    jobs: list[Job] = []
    seen: set[str] = set()

    urls_to_try = [
        "https://www.forasna.com/jobs?q=cybersecurity",
        "https://www.forasna.com/jobs?q=security+analyst",
        "https://www.forasna.com/jobs/security",
    ]

    for url in urls_to_try:
        try:
            resp = requests.get(url, headers=_H, timeout=10)
            if resp.status_code != 200:
                continue
            html = resp.text
        except Exception as exc:
            log.debug("Forasna %s: %s", url, exc)
            continue

        for href, anchor_text in re.findall(
            r'<a[^>]+href="(/[^"]*job[^"]*)"[^>]*>(.*?)</a>',
            html, re.IGNORECASE | re.DOTALL
        ):
            title = _clean(anchor_text)
            if not title or not _is_sec(title):
                continue
            full_url = urllib.parse.urljoin("https://www.forasna.com", href)
            if full_url in seen:
                continue
            seen.add(full_url)
            job = _make_job(
                title=title, company="Forasna Employer",
                location="Egypt", url=full_url,
                source="forasna", priority=26,
            )
            if job:
                jobs.append(job)

        time.sleep(0.3)

    log.info("Forasna: %d jobs", len(jobs))
    return jobs


# ── 5. LinkedIn Egypt Company Pages (Cybersecurity specific) ────────────────
def fetch_linkedin_egypt_companies_direct() -> list[Job]:
    """
    Fetch directly from LinkedIn Egypt-based cybersecurity companies' jobs pages.
    These are Egyptian companies that regularly post security jobs.
    """
    jobs: list[Job] = []
    seen: set[str] = set()

    # Egyptian cybersecurity & tech companies with known LinkedIn presence
    EGYPT_CYBER_COMPANIES = [
        # Security-focused
        ("CyberTalents", "cybertalents"),
        ("Solutionz Group Egypt", "solutionz-group"),
        ("Secured Globe", "secured-globe"),
        ("Help AG Egypt", "help-ag"),
        # Big tech Egypt offices
        ("IBM Egypt", "ibm"),
        ("Cisco Egypt", "cisco"),
        ("Orange Egypt", "orange-egypt"),
        ("Vodafone Egypt", "vodafone-egypt"),
        ("Etisalat Egypt (e&)", "etisalat-egypt"),
        # Telecom security teams
        ("We Telecom", "we-telecom-egypt"),
        # IT integrators with security divisions
        ("ITWorx", "itworx"),
        ("Raya IT", "raya-information-technology"),
        ("Xceed", "xceed"),
        # Banks (large security teams)
        ("National Bank of Egypt", "national-bank-of-egypt"),
        ("CIB Egypt", "cib-egypt"),
        ("Banque Misr", "banque-misr"),
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    }

    for company_name, slug in EGYPT_CYBER_COMPANIES:
        url = f"https://www.linkedin.com/company/{slug}/jobs/"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code not in (200, 301, 302):
                continue
            html = resp.text
        except Exception as exc:
            log.debug("LinkedIn company %s: %s", company_name, exc)
            continue

        # Extract job IDs from the company page
        job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        if not job_ids:
            job_ids = re.findall(r'/jobs/view/(\d+)/', html)

        for job_id in list(dict.fromkeys(job_ids))[:10]:
            url_j = f"https://www.linkedin.com/jobs/view/{job_id}/"
            if url_j in seen:
                continue

            # Try to get title from the page content
            titles = re.findall(
                r'<h2[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)',
                html
            )
            title = titles[0].strip() if titles else f"Security Job at {company_name}"

            if not _is_sec(title):
                continue

            seen.add(url_j)
            job = _make_job(
                title=title, company=company_name,
                location="Egypt", url=url_j,
                source="linkedin_eg_company",
                description=f"Security role at {company_name} (Egypt)",
                priority=12,  # High priority - LinkedIn + Egypt company
            )
            if job:
                job.tags = ["linkedin", "egypt", "egypt_company", "linkedin_eg_company"]
                jobs.append(job)

        time.sleep(0.5)

    log.info("LinkedIn Egypt Companies: %d jobs", len(jobs))
    return jobs


# ── Main aggregator ───────────────────────────────────────────────────────────
def fetch_egypt_boards() -> list[Job]:
    """Aggregate all Egyptian job boards. 3-minute budget."""
    BUDGET = 180
    start = time.time()
    all_jobs: list[Job] = []

    fetchers = [
        ("Wazzif", fetch_wazzif),
        ("Akhtaboot Egypt", fetch_akhtaboot_egypt),
        ("DrJobPro Egypt", fetch_drjobpro_egypt),
        ("Forasna", fetch_forasna),
    ]

    for name, fn in fetchers:
        if time.time() - start > BUDGET:
            log.info("egypt_boards: 3-min budget exhausted at '%s'", name)
            break
        try:
            results = fn()
            all_jobs.extend(results)
        except Exception as exc:
            log.warning("egypt_boards: %s failed: %s", name, exc)

    log.info("egypt_boards total: %d jobs", len(all_jobs))
    return all_jobs
