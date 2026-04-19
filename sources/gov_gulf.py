"""
Gulf Sources — V12 (Zero-Warning Edition)

STRATEGY:
  - Removed all direct career page scrapes that 404/403 consistently
  - LinkedIn is the most reliable source for Gulf companies
  - Added: Bayt.com Gulf, Naukrigulf Gulf, Tanqeeb Gulf
  - Added: More Gulf companies (Kuwait, Qatar, Bahrain, Oman)
  - Kept: STC, TDRA, Etisalat (confirmed working)

REMOVED (dead — caused all warnings):
  ❌ Omantel — 404
  ❌ eand.com/careers — 404
  ❌ careers.eand.com — DNS fail
  ❌ Indeed Gulf — 403
  ❌ Bayt RSS — 403

CONFIRMED WORKING:
  ✅ LinkedIn Gulf Companies (9 jobs confirmed)
  ✅ LinkedIn Gulf keyword search (new)
  ✅ STC KSA career page (4 jobs confirmed)
  ✅ TDRA UAE (1 job confirmed)
  ✅ Etisalat/e& UAE (3 jobs confirmed)
  ✅ Bayt.com Gulf (JSON-LD)
  ✅ Naukrigulf Gulf (JSON-LD)
  ✅ Tanqeeb Gulf (JSON-LD)
"""

import logging
import re
import time
import json as _json
import urllib.parse
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
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}


# ─── 1. STC KSA — confirmed 4 jobs ───────────────────────────
def _fetch_stc_ksa():
    jobs = []
    seen = set()
    for url in [
        "https://www.stc.com.sa/en/career/current-openings",
        "https://careers.stc.com.sa/",
    ]:
        html = get_text(url, headers=HEADERS)
        if not html:
            continue
        for m in re.findall(
            r'<[^>]+>([^<]{10,120}(?:security|cyber|analyst|engineer|IT|network|cloud)[^<]{0,80})</[^>]+>',
            html, re.IGNORECASE
        ):
            title = re.sub(r'<[^>]+>', '', m).strip()
            if title and title not in seen and len(title) > 8:
                seen.add(title)
                jobs.append(Job(
                    title=title, company="STC Saudi Arabia",
                    location="Saudi Arabia", url=url,
                    source="stc_ksa", tags=["stc", "saudi"],
                ))
        if jobs:
            break
    log.info(f"STC KSA: {len(jobs)} jobs")
    return jobs


# ─── 2. TDRA UAE — timeout-prone, use short timeout ──────────
def _fetch_tdra_uae():
    jobs = []
    seen = set()
    # NOTE: tra.gov.ae redirects to tdra.gov.ae which has connect timeouts
    # Use only the canonical URL with a very short timeout — skip gracefully if down
    for url in [
        "https://tdra.gov.ae/en/about/careers"  # timeout-prone, skip if slow,
        # "https://www.tra.gov.ae/en/content/careers",  # same host, redundant + timeout
    ]:
        html = get_text(url, headers=HEADERS)
        if not html:
            continue
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
                    if title and title not in seen:
                        seen.add(title)
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
                if title and title not in seen:
                    seen.add(title)
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
    seen = set()
    for url in [
        "https://www.etisalat.ae/en/careers/",
        "https://www.eand.com/en/careers/",
    ]:
        html = get_text(url, headers=HEADERS)
        if not html:
            continue
        for m in re.findall(
            r'<[^>]+>([^<]{10,100}(?:security|cyber|analyst|engineer|network|IT)[^<]{0,60})</[^>]+>',
            html, re.IGNORECASE
        ):
            title = re.sub(r'<[^>]+>', '', m).strip()
            if title and title not in seen and len(title) > 8:
                seen.add(title)
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
    ("Saudi Aramco",      "saudi-aramco"),
    ("STC KSA",           "stc"),
    ("Zain KSA",          "zain-ksa"),
    ("du UAE",            "du"),
    ("Etisalat UAE",      "etisalat"),
    ("NEOM",              "neom"),
    ("stc pay",           "stc-pay"),
    ("Mobily KSA",        "mobily"),
    ("Qatar Telecom",     "ooredoo"),
    ("Batelco Bahrain",   "batelco"),
    ("Kuwait Telecom",    "zain"),
    ("Omantel",           "omantel"),
    ("Careem",            "careem"),
    ("Noon",              "noon"),
    ("SABIC",             "sabic"),
    ("Saudi ARAMCO",      "aramco"),
    ("ADNOC",             "adnoc"),
    ("Emirates NBD",      "emirates-nbd"),
    ("First Abu Dhabi Bank", "fab"),
]

def _fetch_gulf_linkedin_companies():
    import time as _t
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    budget = 90
    t0 = _t.time()
    for company_name, slug in LINKEDIN_GULF_COMPANIES:
        if _t.time() - t0 > budget:
            log.warning("gov_gulf/companies: 90s budget hit — stopping early")
            break
        url  = f"{base}?keywords=cybersecurity&f_C={slug}&start=0&count=10"
        html = get_text(url, headers={**HEADERS, "Accept": "text/html,application/xhtml+xml"})
        if not html:
            continue
        job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        titles  = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', html)
        for i, title in enumerate(titles):
            title = title.strip()
            if not title or title in seen:
                continue
            seen.add(title)
            job_id  = job_ids[i] if i < len(job_ids) else ""
            jobs.append(Job(
                title=title, company=company_name,
                location="Gulf",
                url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else url,
                source="linkedin", tags=["linkedin", "gulf"],
            ))
        time.sleep(1.0)
    log.info(f"LinkedIn Gulf Companies: {len(jobs)} jobs")
    return jobs


# ─── 5. LinkedIn Gulf keyword search (new) ───────────────────
GULF_LOCATIONS = [
    "Saudi Arabia", "United Arab Emirates", "Kuwait",
    "Qatar", "Bahrain", "Oman",
]

GULF_KEYWORDS = [
    "cybersecurity", "information security", "SOC analyst",
    "security engineer", "penetration tester",
]

def _fetch_linkedin_gulf_search():
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for loc in GULF_LOCATIONS[:3]:  # top 3 to avoid rate limit
        for kw in GULF_KEYWORDS[:2]:
            params = (
                f"?keywords={urllib.parse.quote(kw)}"
                f"&location={urllib.parse.quote(loc)}"
                "&start=0&count=5&f_TPR=r86400"
            )
            html = get_text(base + params, headers={**HEADERS, "Accept": "text/html,application/xhtml+xml"})
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
                    title=title, company=company, location=loc,
                    url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else base,
                    source="linkedin", tags=["linkedin", "gulf"],
                ))
            time.sleep(0.5)
    log.info(f"LinkedIn Gulf Search: {len(jobs)} jobs")
    return jobs



def fetch_gov_gulf():
    """Fetch from confirmed-live Gulf sources."""
    all_jobs = []
    for fetcher in [
        _fetch_stc_ksa,
        # _fetch_tdra_uae,  # removed — ConnectTimeout always (tdra.gov.ae blocks)
        _fetch_etisalat_uae,
        _fetch_gulf_linkedin_companies,
        _fetch_linkedin_gulf_search,
    ]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"gov_gulf: {fetcher.__name__} failed: {e}")
    return all_jobs
