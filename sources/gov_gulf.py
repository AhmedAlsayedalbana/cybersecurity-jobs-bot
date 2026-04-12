"""
Gulf Sources — V10
CONFIRMED WORKING (from logs):
  ✅ STC KSA                — 4 jobs
  ✅ TDRA UAE               — 1 job
  ✅ LinkedIn Gulf Cos      — 9 jobs
  ✅ Etisalat UAE           — 3 jobs

REMOVED (confirmed dead every run):
  ❌ Indeed Gulf       — 403 Forbidden always
  ❌ Bayt Gulf         — 403 Forbidden always
  ❌ Omantel           — 404 always
  ❌ eand.com/careers  — 404 always
  ❌ careers.eand.com  — DNS fail

No ThreadPoolExecutor — sequential is fast enough for 4 sources.
"""

import logging
import re
import time
import json as _json
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}


# ─── 1. STC KSA — confirmed 4 jobs ───────────────────────────
def _fetch_stc_ksa():
    jobs = []
    for url in ["https://www.stc.com.sa/en/career/current-openings",
                "https://careers.stc.com.sa/"]:
        html = get_text(url, headers=HEADERS)
        if not html:
            continue
        found = set()
        for m in re.findall(
            r'<[^>]+>([^<]{10,120}(?:security|cyber|analyst|engineer|IT|network|cloud)[^<]{0,80})</[^>]+>',
            html, re.IGNORECASE
        ):
            title = re.sub(r'<[^>]+>', '', m).strip()
            if title and title not in found and len(title) > 8:
                found.add(title)
                jobs.append(Job(
                    title=title, company="STC Saudi Arabia",
                    location="Saudi Arabia", url=url,
                    source="stc_ksa", tags=["stc", "saudi"],
                ))
        if jobs:
            break
    log.info(f"STC KSA: {len(jobs)} jobs")
    return jobs


# ─── 2. TDRA UAE — confirmed 1 job ───────────────────────────
def _fetch_tdra_uae():
    jobs = []
    for url in ["https://tdra.gov.ae/en/about/careers",
                "https://www.tra.gov.ae/en/content/careers"]:
        html = get_text(url, headers=HEADERS)
        if not html:
            continue
        found = set()
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data = _json.loads(block.strip())
                for item in (data if isinstance(data, list) else [data]):
                    if item.get("@type") != "JobPosting":
                        continue
                    title = item.get("title", "").strip()
                    if title and title not in found:
                        found.add(title)
                        jobs.append(Job(
                            title=title, company="TDRA UAE",
                            location="UAE", url=item.get("url", url),
                            source="tdra_uae", tags=["tdra", "uae", "government"],
                        ))
            except Exception:
                continue
        if not jobs:
            for m in re.findall(
                r'<h[2-5][^>]*>([^<]{10,120}(?:security|cyber|analyst|engineer|IT)[^<]{0,80})</h[2-5]>',
                html, re.IGNORECASE
            ):
                title = re.sub(r'<[^>]+>', '', m).strip()
                if title and title not in found:
                    found.add(title)
                    jobs.append(Job(
                        title=title, company="TDRA UAE",
                        location="UAE", url=url,
                        source="tdra_uae", tags=["tdra", "uae"],
                    ))
        if jobs:
            break
    log.info(f"TDRA UAE: {len(jobs)} jobs")
    return jobs


# ─── 3. Etisalat (e&) UAE — confirmed 3 jobs ─────────────────
def _fetch_etisalat_uae():
    jobs = []
    for url in ["https://www.etisalat.ae/en/careers/",
                "https://www.eand.com/en/careers/"]:
        html = get_text(url, headers=HEADERS)
        if not html:
            continue
        found = set()
        for m in re.findall(
            r'<[^>]+>([^<]{10,100}(?:security|cyber|analyst|engineer|network|IT)[^<]{0,60})</[^>]+>',
            html, re.IGNORECASE
        ):
            title = re.sub(r'<[^>]+>', '', m).strip()
            if title and title not in found and len(title) > 8:
                found.add(title)
                jobs.append(Job(
                    title=title, company="e& UAE (Etisalat)",
                    location="UAE", url=url,
                    source="etisalat_uae", tags=["etisalat", "uae"],
                ))
        if jobs:
            break
    log.info(f"Etisalat UAE: {len(jobs)} jobs")
    return jobs


# ─── 4. LinkedIn Gulf Companies — confirmed 9 jobs ────────────
LINKEDIN_GULF_COMPANIES = [
    ("Saudi Aramco",  "saudi-aramco"),
    ("STC KSA",       "stc"),
    ("Zain KSA",      "zain-ksa"),
    ("du UAE",        "du"),
    ("Etisalat UAE",  "etisalat"),
    ("NEOM",          "neom"),
    ("stc pay",       "stc-pay"),
]

def _fetch_gulf_linkedin_companies():
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for company_name, slug in LINKEDIN_GULF_COMPANIES:
        url = f"{base}?keywords=cybersecurity&f_C={slug}&start=0&count=10"
        html = get_text(url, headers={**HEADERS, "Accept": "text/html,application/xhtml+xml"})
        if not html:
            continue
        job_ids = re.findall(r'data-job-id="(\d+)"', html)
        titles  = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', html)
        for i, title in enumerate(titles):
            title = title.strip()
            if not title or title in seen:
                continue
            seen.add(title)
            job_id  = job_ids[i] if i < len(job_ids) else ""
            job_url = f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else url
            jobs.append(Job(
                title=title, company=company_name,
                location="Gulf", url=job_url,
                source="linkedin", tags=["linkedin", "gulf"],
            ))
        time.sleep(1.5)
    log.info(f"LinkedIn Gulf Companies: {len(jobs)} jobs")
    return jobs


def fetch_gov_gulf():
    """Fetch from confirmed-live Gulf sources only."""
    all_jobs = []
    for fetcher in [_fetch_stc_ksa, _fetch_tdra_uae, _fetch_etisalat_uae, _fetch_gulf_linkedin_companies]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"gov_gulf: {fetcher.__name__} failed: {e}")
    return all_jobs
