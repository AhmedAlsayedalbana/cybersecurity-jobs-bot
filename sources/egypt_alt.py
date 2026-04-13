"""
Egypt Alternative Sources — V12 (Professional System)
Optimized for Egypt Private Sector, Banks, and Local Job Boards.
"""

import logging
import re
import json
from models import Job
from sources.http_utils import get_text, get_json
from config import EG_PRIVATE_COMPANIES

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}

SEC_KEYWORDS = [
    "cybersecurity", "security analyst", "soc analyst", "penetration",
    "information security", "network security", "security engineer",
    "grc", "dfir", "cloud security", "devsecops", "malware", "forensic",
    "أمن المعلومات", "أمن سيبراني", "اختبار اختراق", "security specialist",
]

def _is_sec(text):
    if not text: return False
    return any(k in text.lower() for k in SEC_KEYWORDS)


# ─── 1. LinkedIn Egypt Search (Smart Fallback) ───────────────
LINKEDIN_EGYPT_SEARCHES = [
    "cybersecurity Egypt", "SOC analyst Egypt",
    "information security Egypt", "security engineer Egypt",
    "penetration tester Egypt", "security specialist Egypt",
]

def _fetch_linkedin_egypt_search():
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for kw in LINKEDIN_EGYPT_SEARCHES:
        params = f"?keywords={kw.replace(' ', '%20')}&location=Egypt&start=0&count=15&f_TPR=r86400"
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
                location="Egypt",
                url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else base,
                source="linkedin", tags=["linkedin", "egypt"],
            ))
    return jobs


# ─── 2. Wuzzuf — Smart HTML Scraper (Silent) ─────────────────
WUZZUF_QUERIES = ["cybersecurity", "information security", "security engineer", "SOC analyst"]

def _fetch_wuzzuf():
    jobs = []
    seen = set()
    for q in WUZZUF_QUERIES:
        page_url = f"https://wuzzuf.net/search/jobs/?q={q.replace(' ', '+')}&a=hpb&l=Egypt"
        html = get_text(page_url, headers=_H)
        if not html:
            continue
        
        # Extract __NEXT_DATA__ for clean JSON
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            try:
                nd = json.loads(m.group(1))
                jobs_list = nd.get("props", {}).get("pageProps", {}).get("jobs", {}).get("data", []) or []
                for item in jobs_list:
                    title   = item.get("title", {}).get("text", "")
                    company = item.get("company", {}).get("name", "")
                    slug    = item.get("slug", "")
                    if not title or slug in seen:
                        continue
                    seen.add(slug)
                    jobs.append(Job(
                        title=title, company=company,
                        location="Egypt",
                        url=f"https://wuzzuf.net/jobs/p/{slug}" if slug else page_url,
                        source="wuzzuf", tags=["wuzzuf", "egypt"],
                    ))
            except:
                pass
    return jobs


# ─── 3. Egypt Private Sector & Banks (Smart Search) ──────────
def _fetch_eg_private_sector():
    """
    Instead of scraping individual pages which break often, 
    we use a targeted LinkedIn search for these specific companies.
    """
    jobs = []
    seen = set()
    # Search for jobs in these companies specifically
    for company in EG_PRIVATE_COMPANIES[:10]: # Top 10 for performance
        kw = f"security {company}"
        base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        params = f"?keywords={kw.replace(' ', '%20')}&location=Egypt&f_TPR=r2592000" # Last month
        html = get_text(base + params, headers=_H)
        if not html: continue
        
        titles = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', html)
        job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        
        for i, title in enumerate(titles):
            title = title.strip()
            if _is_sec(title) and title not in seen:
                seen.add(title)
                job_id = job_ids[i] if i < len(job_ids) else ""
                jobs.append(Job(
                    title=title, company=company,
                    location="Egypt",
                    url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else "https://www.linkedin.com",
                    source="eg_private", tags=["egypt", "private_sector"],
                ))
    return jobs


def fetch_egypt_alt():
    all_jobs = []
    for fetcher in [
        _fetch_linkedin_egypt_search,
        _fetch_wuzzuf,
        _fetch_eg_private_sector,
    ]:
        try:
            all_jobs.extend(fetcher())
        except:
            pass # Silent failure
    return all_jobs
