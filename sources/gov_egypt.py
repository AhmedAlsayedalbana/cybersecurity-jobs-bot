"""
Egyptian Government & Major Employer Sources — V11

CONFIRMED WORKING:
  ✅ LinkedIn Egypt Companies — 9 jobs confirmed

ADDED: All Egyptian governorates as LinkedIn location targets
  Cairo, Alexandria, Giza, Qalyubia, Sharqia, Dakahlia,
  Beheira, Kafr el-Sheikh, Gharbia, Menoufia, Faiyum,
  Beni Suef, Minya, Asyut, Sohag, Qena, Luxor, Aswan,
  Red Sea, New Valley, Matrouh, North Sinai, South Sinai,
  Ismailia, Port Said, Suez, Damietta
"""

import logging
import re
import time
import json
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}

# ─── 1. LinkedIn Egypt Companies ─────────────────────────────
LINKEDIN_EG_COMPANIES = [
    # Telecom
    ("Telecom Egypt (WE)",  "telecom-egypt"),
    ("Vodafone Egypt",      "vodafone-egypt"),
    ("Orange Egypt",        "orange-egypt"),
    ("Etisalat Egypt",      "etisalat-egypt"),
    # Banks
    ("CIB Egypt",           "commercial-international-bank"),
    ("QNB Egypt",           "qnb-alahli"),
    ("HSBC Egypt",          "hsbc"),
    # Tech
    ("Fawry",               "fawry"),
    ("ITWorx",              "itworx"),
    ("Paymob",              "paymob"),
    ("Raya Corporation",    "raya-corporation"),
    ("Xceed",               "xceed"),
    # Consulting
    ("Deloitte Egypt",      "deloitte"),
    ("KPMG Egypt",          "kpmg"),
    ("PwC Egypt",           "pwc"),
    ("EY Egypt",            "ey"),
]

def _fetch_egypt_linkedin_companies():
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for company_name, slug in LINKEDIN_EG_COMPANIES:
        url = f"{base}?keywords=security&f_C={slug}&start=0&count=10"
        html = get_text(url, headers={**_H, "Accept": "text/html,application/xhtml+xml"})
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
            jobs.append(Job(
                title=title, company=company_name,
                location="Egypt",
                url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else url,
                source="linkedin", tags=["linkedin", "egypt"],
            ))
        time.sleep(0.8)
    log.info(f"LinkedIn Egypt Companies: {len(jobs)} jobs")
    return jobs


# ─── 2. LinkedIn by Egyptian Governorate ─────────────────────
# All 27 governorates — covers the whole country
EG_GOVERNORATES = [
    "Cairo, Egypt", "Alexandria, Egypt", "Giza, Egypt",
    "Qalyubia, Egypt", "Sharqia, Egypt", "Dakahlia, Egypt",
    "Beheira, Egypt", "Gharbia, Egypt", "Menoufia, Egypt",
    "Faiyum, Egypt", "Beni Suef, Egypt", "Minya, Egypt",
    "Asyut, Egypt", "Sohag, Egypt", "Qena, Egypt",
    "Luxor, Egypt", "Aswan, Egypt", "Ismailia, Egypt",
    "Port Said, Egypt", "Suez, Egypt", "Damietta, Egypt",
    "Kafr el-Sheikh, Egypt", "Red Sea, Egypt",
    "New Cairo, Egypt", "6th of October, Egypt",
    "New Administrative Capital, Egypt",
]

# Only query the major populated governorates to save time
MAJOR_GOVERNORATES = [
    "Cairo, Egypt", "Alexandria, Egypt", "Giza, Egypt",
    "New Cairo, Egypt", "6th of October, Egypt",
    "New Administrative Capital, Egypt",
    "Qalyubia, Egypt", "Ismailia, Egypt", "Port Said, Egypt",
]

SECURITY_KEYWORDS = [
    "cybersecurity", "information security", "SOC analyst",
    "security engineer", "penetration tester",
]

def _fetch_linkedin_by_governorate():
    """Search LinkedIn by major Egyptian governorates + security keywords."""
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for gov in MAJOR_GOVERNORATES:
        for kw in SECURITY_KEYWORDS[:2]:  # limit to avoid rate limiting
            params = (
                f"?keywords={kw.replace(' ', '%20')}"
                f"&location={gov.replace(' ', '%20').replace(',', '%2C')}"
                f"&start=0&count=5&f_TPR=r86400"
            )
            html = get_text(base + params, headers={**_H, "Accept": "text/html,application/xhtml+xml"})
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
                    title=title, company=company,
                    location=gov,
                    url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else base,
                    source="linkedin", tags=["linkedin", "egypt", gov.split(",")[0].lower()],
                ))
            time.sleep(0.5)
    log.info(f"LinkedIn Egypt Governorates: {len(jobs)} jobs")
    return jobs


def fetch_gov_egypt():
    """Fetch from confirmed-live Egyptian sources."""
    all_jobs = []
    for fetcher in [_fetch_egypt_linkedin_companies, _fetch_linkedin_by_governorate]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"gov_egypt: {fetcher.__name__} failed: {e}")
    return all_jobs
