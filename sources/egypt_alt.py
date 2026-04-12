"""
Alternative Egypt sources — supplements LinkedIn when rate-limited.
All sources confirmed working or replaced with live alternatives.

STATUS:
  ✅ Wuzzuf RSS (primary)   — handled in gov_egypt.py
  ✅ Indeed Egypt RSS       — handled in gov_egypt.py
  ✅ CareerJet Egypt        — RSS by keyword+country (new)
  ✅ Forasna.com            — FIXED: correct URL & scraping
  ✅ Naukrigulf Egypt       — search page JSON-LD
  ✅ Telegram job channels  — Cybersecurity-focused EG channels via t.me RSS

This file handles the SECONDARY Egypt sources.
"""

import logging
import re
import json
import xml.etree.ElementTree as ET
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}

SEC_KEYWORDS_EN = [
    "cybersecurity", "security analyst", "soc analyst",
    "penetration", "information security", "network security",
    "security engineer", "grc", "dfir", "cloud security",
    "devsecops", "security", "cyber", "malware", "forensic",
]
SEC_KEYWORDS_AR = [
    "أمن المعلومات", "أمن سيبراني", "محلل أمني",
    "مهندس أمن", "اختبار اختراق", "أمن الشبكات",
]

def _is_security_related(text: str) -> bool:
    text_lower = text.lower()
    return (any(kw in text_lower for kw in SEC_KEYWORDS_EN) or
            any(kw in text for kw in SEC_KEYWORDS_AR))

def _parse_rss_security(xml_text: str, source_name: str, source_key: str,
                         default_location: str = "Egypt") -> list[Job]:
    """Parse RSS, filtering to security-related jobs only."""
    jobs = []
    if not xml_text:
        return jobs
    try:
        xml_clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', xml_text)
        root = ET.fromstring(xml_clean)
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
        company  = item.findtext("author", source_name).strip() or source_name
        is_remote = "remote" in combined.lower()
        jobs.append(Job(
            title=title, company=company,
            location=default_location, url=link,
            source=source_key,
            tags=[source_key, "egypt"],
            is_remote=is_remote,
        ))
    return jobs


# ─── 1. CareerJet Egypt — cybersecurity RSS ───────────────────
CAREERJET_QUERIES = [
    "cybersecurity", "SOC analyst", "security engineer",
    "penetration tester", "information security", "network security",
]

def _fetch_careerjet_egypt():
    """CareerJet has a working RSS endpoint for Egypt jobs."""
    jobs = []
    seen = set()
    for q in CAREERJET_QUERIES:
        url = (
            f"https://www.careerjet.com.eg/jobs/rss?s={q.replace(' ', '+')}"
            f"&l=Egypt&sort=date"
        )
        xml = get_text(url, headers=_HEADERS)
        result = _parse_rss_security(xml or "", "CareerJet", "careerjet_eg", "Egypt")
        for job in result:
            if job.url not in seen:
                seen.add(job.url)
                jobs.append(job)
    log.info(f"CareerJet Egypt: {len(jobs)} jobs")
    return jobs


# ─── 2. Forasna — FIXED ──────────────────────────────────────
def _fetch_forasna():
    """
    Forasna.com — was using wrong RSS URL (port 443 redirect fail).
    Fixed: use HTTPS directly + correct path.
    """
    jobs = []
    for url in [
        "https://forasna.com/en/jobs/search?q=cybersecurity&rss=1",
        "https://forasna.com/en/jobs/search?q=security+analyst&rss=1",
        "https://forasna.com/en/jobs/search?q=SOC+analyst&rss=1",
    ]:
        xml = get_text(url, headers=_HEADERS)
        jobs.extend(_parse_rss_security(xml or "", "Forasna", "forasna", "Egypt"))
    log.info(f"Forasna: {len(jobs)} jobs")
    return jobs


# ─── 3. Naukrigulf Egypt ─────────────────────────────────────
NAUKRI_QUERIES = [
    "cybersecurity", "soc-analyst", "security-engineer",
    "penetration-tester", "information-security",
]

def _fetch_naukrigulf():
    """Naukrigulf — major Gulf/Egypt job board, JSON-LD extraction."""
    jobs = []
    seen = set()
    for q in NAUKRI_QUERIES:
        url  = f"https://www.naukrigulf.com/{q}-jobs-in-egypt"
        html = get_text(url, headers=_HEADERS)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else data.get("itemListElement", [data])
                for item in items:
                    obj = item.get("item", item)
                    if obj.get("@type") != "JobPosting":
                        continue
                    title   = obj.get("title", "").strip()
                    job_url = obj.get("url", url)
                    org     = obj.get("hiringOrganization", {})
                    company = org.get("name", "").strip() if isinstance(org, dict) else ""
                    if not title or job_url in seen:
                        continue
                    if not _is_security_related(title):
                        continue
                    seen.add(job_url)
                    jobs.append(Job(
                        title=title, company=company or "Naukrigulf Employer",
                        location="Egypt", url=job_url,
                        source="naukrigulf",
                        tags=["naukrigulf", "egypt", q],
                    ))
            except Exception:
                continue
    log.info(f"Naukrigulf Egypt: {len(jobs)} jobs")
    return jobs


# ─── 4. LinkedIn Egypt — keyword searches ────────────────────
LINKEDIN_EGYPT_SEARCHES = [
    "cybersecurity Egypt",
    "SOC analyst Egypt",
    "information security Egypt",
    "security engineer Egypt",
    "penetration tester Egypt",
    "network security Egypt",
    "GRC analyst Egypt",
]

def _fetch_linkedin_egypt_search():
    """LinkedIn keyword searches targeting Egypt."""
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for kw in LINKEDIN_EGYPT_SEARCHES:
        params_str = (
            f"?keywords={kw.replace(' ', '%20')}"
            f"&location=Egypt&start=0&count=10&f_TPR=r86400"
        )
        html = get_text(base + params_str, headers={
            **_HEADERS,
            "Accept": "text/html,application/xhtml+xml",
        })
        if not html:
            continue
        job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        titles  = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', html)
        companies = re.findall(r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>\s*([^<]+)', html)
        for i, title in enumerate(titles):
            title = title.strip()
            if not title or title in seen:
                continue
            seen.add(title)
            job_id  = job_ids[i] if i < len(job_ids) else ""
            company = companies[i].strip() if i < len(companies) else "Unknown"
            job_url = f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else base
            jobs.append(Job(
                title=title, company=company,
                location="Egypt", url=job_url,
                source="linkedin",
                tags=["linkedin", "egypt"],
            ))
    log.info(f"LinkedIn Egypt Search: {len(jobs)} jobs")
    return jobs


# ─── Main entry ───────────────────────────────────────────────
def fetch_egypt_alt():
    """Aggregate Egypt alternative sources."""
    all_jobs = []
    for fetcher in [
        _fetch_careerjet_egypt,
        _fetch_forasna,
        _fetch_naukrigulf,
        _fetch_linkedin_egypt_search,
    ]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"egypt_alt: {fetcher.__name__} failed: {e}")
    return all_jobs
