"""
Egyptian Government & Major Employer Sources — V12 FAST

KEY FIX v27: Added TIME BUDGET to prevent hanging.
  - Companies: 60s max (was unlimited)
  - Governorates: 45s max, only 3 top cities × 2 keywords (was 9 × 5)

gov_egypt now focuses on GOVERNMENT companies only.
Private sector is handled by egypt_alt.py (avoids duplicate requests).
"""

import logging
import re
import time
import urllib.parse
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

JOBS_API = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

# Government & public sector companies only (private in egypt_alt.py)
LINKEDIN_EG_COMPANIES = [
    ("Telecom Egypt (WE)",  "telecom-egypt"),
    ("Vodafone Egypt",      "vodafone-egypt"),
    ("Orange Egypt",        "orange-egypt"),
    ("Etisalat Egypt",      "etisalatmisr"),
    ("CIB Egypt",           "commercial-international-bank"),
    ("QNB Egypt",           "qnb-alahli"),
    ("HSBC Egypt",          "hsbc"),
    ("Fawry",               "fawry"),
    ("ITWorx",              "itworx"),
    ("Paymob",              "paymob"),
    ("Raya Corporation",    "raya-corporation"),
    ("Xceed",               "xceed"),
    ("Deloitte Egypt",      "deloitte"),
    ("KPMG Egypt",          "kpmg"),
    ("PwC Egypt",           "pwc"),
    ("EY Egypt",            "ey"),
    ("MCIT Egypt",          "mcit-egypt"),
    ("ITIDA",               "itida"),
    ("EG-CERT",             "eg-cert"),
    ("Central Bank Egypt",  "central-bank-of-egypt"),
]


def _fetch_egypt_linkedin_companies():
    jobs = []
    seen = set()
    budget = 90   # seconds max — was unlimited
    t0 = time.time()

    for company_name, slug in LINKEDIN_EG_COMPANIES:
        if time.time() - t0 > budget:
            log.warning("gov_egypt/companies: 90s budget hit — stopping early")
            break
        url = f"{JOBS_API}?keywords=security&f_C={slug}&start=0&count=10"
        html = get_text(url, headers=_H)
        if not html:
            continue
        job_ids  = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        titles   = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', html)
        for i, title in enumerate(titles):
            title = title.strip()
            if not title or title in seen:
                continue
            seen.add(title)
            job_id = job_ids[i] if i < len(job_ids) else ""
            jobs.append(Job(
                title=title, company=company_name,
                location="Egypt",
                url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else url,
                source="linkedin", tags=["linkedin", "egypt"],
            ))

    log.info(f"LinkedIn Egypt Companies: {len(jobs)} jobs")
    return jobs


# 3 major tech hubs × 2 keywords = 6 requests max (was 9 × 5 = 45)
TOP_TECH_HUBS = [
    "New Cairo, Egypt",
    "New Administrative Capital, Egypt",
    "Cairo, Egypt",
]

SECURITY_KEYWORDS = [
    "cybersecurity",
    "information security",
]


def _fetch_linkedin_by_governorate():
    jobs = []
    seen = set()
    budget = 45   # seconds max
    t0 = time.time()

    for gov in TOP_TECH_HUBS:
        for kw in SECURITY_KEYWORDS:
            if time.time() - t0 > budget:
                log.warning("gov_egypt/governorates: 45s budget hit — stopping early")
                break
            params = (
                f"?keywords={urllib.parse.quote(kw)}"
                f"&location={urllib.parse.quote(gov)}"
                "&start=0&count=5&f_TPR=r86400"
            )
            html = get_text(JOBS_API + params, headers=_H)
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
                jobs.append(Job(
                    title=title, company=company, location=gov,
                    url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else JOBS_API,
                    source="linkedin", tags=["linkedin", "egypt", gov.split(",")[0].lower()],
                ))

    log.info(f"LinkedIn Egypt Governorates: {len(jobs)} jobs")
    return jobs


def fetch_gov_egypt():
    """Fetch from confirmed-live Egyptian sources. Both fetchers have time budgets."""
    all_jobs = []
    for fetcher in [_fetch_egypt_linkedin_companies, _fetch_linkedin_by_governorate]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"gov_egypt: {fetcher.__name__} failed: {e}")
    return all_jobs
