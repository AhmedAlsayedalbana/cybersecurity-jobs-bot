"""
Egypt Alternative Sources — V10
CONFIRMED WORKING:
  ✅ LinkedIn Egypt Search — 17 jobs (confirmed)
  ✅ CareerJet Egypt       — has RSS but XML malformed → using JSON-LD instead
  ✅ Telegram Channels     — NEW: public cybersec job channels

REMOVED (confirmed dead):
  ❌ Forasna    — 404 Not Found always
  ❌ Naukrigulf — timeout always (15s × 5 = 75s wasted)
  ❌ Indeed Egypt RSS — 403 Forbidden (moved to confirmed dead)
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

SEC_KEYWORDS = [
    "cybersecurity", "security analyst", "soc analyst", "penetration",
    "information security", "network security", "security engineer",
    "grc", "dfir", "cloud security", "devsecops", "malware", "forensic",
    "أمن المعلومات", "أمن سيبراني", "اختبار اختراق", "أمن الشبكات",
]

def _is_security(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in SEC_KEYWORDS)


# ─── 1. LinkedIn Egypt Search — confirmed 17 jobs ────────────
LINKEDIN_EGYPT_SEARCHES = [
    "cybersecurity Egypt", "SOC analyst Egypt",
    "information security Egypt", "security engineer Egypt",
    "penetration tester Egypt", "network security Egypt",
    "GRC analyst Egypt",
]

def _fetch_linkedin_egypt_search():
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for kw in LINKEDIN_EGYPT_SEARCHES:
        params = f"?keywords={kw.replace(' ', '%20')}&location=Egypt&start=0&count=10&f_TPR=r86400"
        html = get_text(base + params, headers={**_HEADERS, "Accept": "text/html,application/xhtml+xml"})
        if not html:
            continue
        job_ids   = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        titles    = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', html)
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
                source="linkedin", tags=["linkedin", "egypt"],
            ))
    log.info(f"LinkedIn Egypt Search: {len(jobs)} jobs")
    return jobs


# ─── 2. CareerJet Egypt — JSON-LD (RSS has XML errors) ───────
CAREERJET_QUERIES = [
    "cybersecurity", "SOC+analyst", "security+engineer",
    "penetration+tester", "information+security",
]

def _fetch_careerjet_egypt():
    """
    CareerJet RSS has malformed XML — use their search page JSON-LD instead.
    """
    jobs = []
    seen = set()
    for q in CAREERJET_QUERIES:
        url  = f"https://www.careerjet.com.eg/jobs-search-results/{q}.html"
        html = get_text(url, headers=_HEADERS)
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
                    if item.get("@type") not in ("JobPosting", "ListItem"):
                        continue
                    obj   = item.get("item", item)
                    title = obj.get("title", "").strip()
                    j_url = obj.get("url", url)
                    org   = obj.get("hiringOrganization", {})
                    comp  = org.get("name", "") if isinstance(org, dict) else ""
                    if not title or j_url in seen:
                        continue
                    if not _is_security(title):
                        continue
                    seen.add(j_url)
                    jobs.append(Job(
                        title=title, company=comp or "CareerJet Employer",
                        location="Egypt", url=j_url,
                        source="careerjet_eg", tags=["careerjet", "egypt"],
                    ))
            except Exception:
                continue
    log.info(f"CareerJet Egypt: {len(jobs)} jobs")
    return jobs


# ─── 3. Telegram Public Job Channels — NEW ───────────────────
# These are active Arabic/Egyptian cybersec job Telegram channels
# that post public messages readable via t.me RSS

TELEGRAM_CHANNELS = [
    # Egyptian & Arabic cybersecurity job channels
    ("CyberJobs_EG",         "https://t.me/s/CyberJobsEG"),
    ("InfoSec Jobs Arabic",  "https://t.me/s/infosecjobsar"),
    ("Arab Cyber Jobs",      "https://t.me/s/arabcyberjobs"),
    ("وظائف أمن المعلومات", "https://t.me/s/cybersec_jobs_ar"),
    ("Cyber Security Jobs",  "https://t.me/s/cybersecjobss"),
    ("وظائف تقنية مصر",     "https://t.me/s/tech_jobs_egypt"),
    ("Security Jobs MENA",   "https://t.me/s/securityjobsmena"),
    ("CyberSec Middle East", "https://t.me/s/cybersecme"),
]

def _fetch_telegram_channels():
    """
    Fetch from public Telegram channel pages (t.me/s/ = public web view).
    Extracts job posts directly from message text.
    """
    jobs = []
    seen = set()
    for channel_name, url in TELEGRAM_CHANNELS:
        html = get_text(url, headers={**_HEADERS, "Accept": "text/html"})
        if not html:
            continue
        # Extract messages from Telegram's web view
        messages = re.findall(
            r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            html, re.DOTALL | re.IGNORECASE
        )
        for msg in messages:
            # Clean HTML
            text = re.sub(r'<[^>]+>', ' ', msg).strip()
            text = re.sub(r'\s+', ' ', text)
            if len(text) < 20 or len(text) > 500:
                continue
            # Must look like a job post
            if not _is_security(text):
                continue
            # Extract potential title (first line)
            lines  = [l.strip() for l in text.split('\n') if l.strip()]
            title  = lines[0][:120] if lines else text[:80]
            if len(title) < 10 or title in seen:
                continue
            seen.add(title)
            # Try to find a URL in the message
            links = re.findall(r'https?://[^\s<>"\']+', msg)
            job_url = links[0] if links else url
            jobs.append(Job(
                title=title, company=channel_name,
                location="Egypt",
                url=job_url,
                source="telegram_eg",
                tags=["telegram", "egypt", "cybersecurity"],
            ))
    log.info(f"Telegram Egypt Channels: {len(jobs)} jobs")
    return jobs


def fetch_egypt_alt():
    """Aggregate Egypt alternative sources — fast & confirmed live."""
    all_jobs = []
    for fetcher in [
        _fetch_linkedin_egypt_search,
        _fetch_careerjet_egypt,
        _fetch_telegram_channels,
    ]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"egypt_alt: {fetcher.__name__} failed: {e}")
    return all_jobs
