"""
Egyptian Sources — V10
CONFIRMED WORKING (from logs):
  ✅ LinkedIn Egypt Companies — 9 jobs
  ✅ LinkedIn Egypt Search    — in egypt_alt.py

REMOVED (confirmed dead every run — wasting time):
  ❌ Indeed Egypt RSS   — 403 Forbidden always
  ❌ Wuzzuf RSS         — 404 Not Found always
  ❌ CBE                — 404 Not Found always
  ❌ Egypt Cyber Firms via Wuzzuf — 0 jobs (site blocks scraping)

TIMEOUT: no ThreadPoolExecutor needed — only 1 fast fetcher left.
"""

import logging
import re
import time
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}

# ─── LinkedIn Egypt Company Pages — CONFIRMED 9 jobs ─────────
LINKEDIN_EG_COMPANIES = [
    ("Telecom Egypt",   "telecom-egypt"),
    ("CIB Bank",        "commercial-international-bank"),
    ("Fawry",           "fawry"),
    ("ITWorx",          "itworx"),
    ("Vodafone Egypt",  "vodafone-egypt"),
    ("Orange Egypt",    "orange-egypt"),
    ("Etisalat Egypt",  "etisalat-egypt"),
    ("Paymob",          "paymob"),
]

def _fetch_egypt_linkedin_companies():
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for company_name, slug in LINKEDIN_EG_COMPANIES:
        url = f"{base}?keywords=security&f_C={slug}&start=0&count=10"
        html = get_text(url, headers={**HEADERS, "Accept": "text/html,application/xhtml+xml"})
        if not html:
            continue
        job_ids  = re.findall(r'data-job-id="(\d+)"', html)
        titles   = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', html)
        for i, title in enumerate(titles):
            title = title.strip()
            if not title or title in seen:
                continue
            seen.add(title)
            job_id  = job_ids[i] if i < len(job_ids) else ""
            job_url = f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else url
            jobs.append(Job(
                title=title, company=company_name,
                location="Egypt", url=job_url,
                source="linkedin",
                tags=["linkedin", "egypt"],
            ))
        time.sleep(1)
    log.info(f"LinkedIn Egypt Companies: {len(jobs)} jobs")
    return jobs


def fetch_gov_egypt():
    """Fetch from confirmed-live Egyptian sources only."""
    return _fetch_egypt_linkedin_companies()
