"""
Gulf Government & Major Institutions — Career Pages Scraper
LIVE SOURCES ONLY (confirmed working from production logs):
  ✅ NCA KSA          — 72 jobs
  ✅ NEOM              — 101 jobs
  ✅ STC KSA           — 23 jobs
  ✅ Omantel           — 22 jobs
  ✅ G42 UAE           — 10 jobs
  ✅ LinkedIn Gulf     — 4 jobs
  ✅ LinkedIn Saudi    — 4 jobs
  ✅ TDRA UAE          — 3 jobs
  ✅ Etisalat UAE      — 1 job

REMOVED (0 jobs / blocked / timed out every run):
  ❌ CITC KSA         (unreachable — [Errno 101])
  ❌ SDAIA            (unreachable — [Errno 101])
  ❌ Saudi Aramco     (read timeout every time)
  ❌ UAE Cyber Council (DNS fail)
  ❌ ADNOC            (404)
  ❌ du UAE           (connect timeout)
  ❌ Ooredoo Qatar    (404)
  ❌ Qatar Foundation (Greenhouse 404)
  ❌ QCERT            (connect timeout)
  ❌ Zain Kuwait      (0 every time)
  ❌ Bahrain EDB      (404)
  ❌ Oman CERT        (0 every time)
  ❌ Tanqeeb          (403 Forbidden — anti-bot)
  ❌ DrJobPro         (404 Not Found)
  ❌ GulfJobsMarket   (connect timeout)
  ❌ Akhtaboot        (0 every time)
"""

import logging
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}


# ─── 1. NCA KSA — 72 jobs confirmed ──────────────────────────
def _fetch_nca_ksa():
    jobs = []
    urls = ["https://nca.gov.sa/en/careers", "https://nca.gov.sa/careers"]
    for url in urls:
        html = get_text(url, headers=HEADERS)
        if not html:
            continue
        found = set()
        for pat in [
            r'<h[2-4][^>]*>([^<]{10,120}(?:security|cyber|analyst|engineer|specialist|officer|architect)[^<]{0,80})</h[2-4]>',
            r'"title"\s*:\s*"([^"]{10,100}(?:security|cyber|analyst|engineer)[^"]{0,80})"',
        ]:
            for m in re.findall(pat, html, re.IGNORECASE):
                title = re.sub(r'<[^>]+>', '', m).strip()
                if title and title not in found:
                    found.add(title)
                    jobs.append(Job(
                        title=title, company="NCA Saudi Arabia",
                        location="Saudi Arabia", url=url,
                        source="nca_ksa", tags=["nca", "government", "saudi"],
                    ))
        if jobs:
            break
    # Also try RSS feed
    feed = get_text("https://nca.gov.sa/en/feed", headers=HEADERS)
    if feed:
        try:
            root = ET.fromstring(feed)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                desc  = item.findtext("description", "") or ""
                if title and link and any(k in (title + desc).lower() for k in ["job", "career", "vacancy", "وظيفة", "hiring"]):
                    jobs.append(Job(
                        title=title, company="NCA Saudi Arabia",
                        location="Saudi Arabia", url=link,
                        source="nca_ksa", tags=["nca", "government", "saudi"],
                    ))
        except ET.ParseError:
            pass
    log.info("NCA KSA: " + str(len(jobs)) + " jobs")
    return jobs


# ─── 2. NEOM — 101 jobs via Greenhouse ───────────────────────
def _fetch_neom():
    """NEOM uses Greenhouse API — very reliable."""
    jobs = []
    # Try multiple Greenhouse slugs
    for slug in ["neom", "neomcompany"]:
        data = get_json(f"https://api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
        if not data or "jobs" not in data:
            continue
        for j in data["jobs"]:
            title = j.get("title", "").strip()
            url   = j.get("absolute_url", "")
            loc_obj = j.get("location", {})
            location = loc_obj.get("name", "Saudi Arabia") if isinstance(loc_obj, dict) else "Saudi Arabia"
            if not title or not url:
                continue
            jobs.append(Job(
                title=title, company="NEOM",
                location=location or "Saudi Arabia",
                url=url, source="neom",
                tags=["neom", "saudi", "ksa"],
            ))
        if jobs:
            break
    log.info("NEOM: " + str(len(jobs)) + " jobs")
    return jobs


# ─── 3. STC KSA — 23 jobs confirmed ──────────────────────────
def _fetch_stc_ksa():
    jobs = []
    urls = [
        "https://www.stc.com.sa/en/career/current-openings",
        "https://careers.stc.com.sa/",
    ]
    for url in urls:
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
                    source="stc_ksa", tags=["stc", "saudi", "telecom"],
                ))
        if jobs:
            break
    log.info("STC KSA: " + str(len(jobs)) + " jobs")
    return jobs


# ─── 4. Omantel — 22 jobs confirmed ──────────────────────────
def _fetch_omantel():
    jobs = []
    urls = [
        "https://www.omantel.om/careers/current-openings",
        "https://www.omantel.om/web/guest/careers",
    ]
    for url in urls:
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
                    title=title, company="Omantel",
                    location="Oman", url=url,
                    source="omantel", tags=["omantel", "oman", "telecom"],
                ))
        if jobs:
            break
    log.info("Omantel: " + str(len(jobs)) + " jobs")
    return jobs


# ─── 5. G42 UAE — Greenhouse API ─────────────────────────────
def _fetch_g42():
    """G42 uses Greenhouse — reliable API."""
    jobs = []
    for slug in ["g42", "g42cloud", "g42-cloud"]:
        data = get_json(f"https://api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
        if not data or "jobs" not in data:
            continue
        for j in data["jobs"]:
            title = j.get("title", "").strip()
            url   = j.get("absolute_url", "")
            loc_obj = j.get("location", {})
            location = loc_obj.get("name", "UAE") if isinstance(loc_obj, dict) else "UAE"
            if not title or not url:
                continue
            jobs.append(Job(
                title=title, company="G42",
                location=location or "UAE",
                url=url, source="g42",
                tags=["g42", "uae", "ai", "tech"],
            ))
        if jobs:
            break
    log.info("G42: " + str(len(jobs)) + " jobs")
    return jobs


# ─── 6. TDRA UAE ──────────────────────────────────────────────
def _fetch_tdra_uae():
    jobs = []
    urls = [
        "https://tdra.gov.ae/en/about-tdra/careers",
        "https://tdra.gov.ae/careers",
    ]
    for url in urls:
        html = get_text(url, headers=HEADERS)
        if not html:
            continue
        found = set()
        for m in re.findall(
            r'<[^>]+>([^<]{10,120}(?:security|cyber|analyst|engineer|IT|specialist)[^<]{0,80})</[^>]+>',
            html, re.IGNORECASE
        ):
            title = re.sub(r'<[^>]+>', '', m).strip()
            if title and title not in found and len(title) > 8:
                found.add(title)
                jobs.append(Job(
                    title=title, company="TDRA UAE",
                    location="UAE", url=url,
                    source="tdra_uae", tags=["tdra", "uae", "government"],
                ))
        if jobs:
            break
    log.info("TDRA UAE: " + str(len(jobs)) + " jobs")
    return jobs


# ─── 7. Etisalat UAE (e&) ────────────────────────────────────
def _fetch_etisalat_uae():
    jobs = []
    urls = [
        "https://www.etisalat.ae/en/careers/current-vacancies.html",
        "https://www.eand.com/en/careers",
    ]
    for url in urls:
        html = get_text(url, headers=HEADERS)
        if not html:
            continue
        found = set()
        for m in re.findall(
            r'<[^>]+>([^<]{10,120}(?:security|cyber|analyst|engineer|cloud|network)[^<]{0,80})</[^>]+>',
            html, re.IGNORECASE
        ):
            title = re.sub(r'<[^>]+>', '', m).strip()
            if title and title not in found and len(title) > 8:
                found.add(title)
                jobs.append(Job(
                    title=title, company="Etisalat UAE (e&)",
                    location="UAE", url=url,
                    source="etisalat_uae", tags=["etisalat", "uae", "telecom"],
                ))
        if jobs:
            break
    log.info("Etisalat UAE: " + str(len(jobs)) + " jobs")
    return jobs


# ─── 8. LinkedIn Gulf Companies ───────────────────────────────
LINKEDIN_GULF_COMPANIES = [
    ("NCA Saudi Arabia", "national-cybersecurity-authority"),
    ("STC KSA",          "saudi-telecom-company"),
    ("Aramex",           "aramex"),
    ("du UAE",           "du-telecom"),
    ("Ooredoo",          "ooredoo"),
]

def _fetch_gulf_linkedin_companies():
    """LinkedIn company pages for Gulf — with polite rate-limit handling."""
    jobs = []
    seen = set()
    for company_name, slug in LINKEDIN_GULF_COMPANIES:
        url = (
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
            "?keywords=security&f_C=" + slug + "&start=0&count=10"
        )
        html = get_text(url, headers={**HEADERS, "Accept": "text/html"})
        if not html:
            continue
        titles  = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', html)
        job_ids = re.findall(r'data-job-id="(\d+)"', html)
        for i, title in enumerate(titles):
            title = title.strip()
            if not title or title in seen:
                continue
            seen.add(title)
            job_id = job_ids[i] if i < len(job_ids) else ""
            job_url = f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else url
            jobs.append(Job(
                title=title, company=company_name,
                location="Gulf", url=job_url,
                source="linkedin", tags=["linkedin", "gulf"],
            ))
        time.sleep(2)
    log.info("LinkedIn Gulf Companies: " + str(len(jobs)) + " jobs")
    return jobs


# ─── 9. Bayt Gulf (direct JSON scrape) ───────────────────────
def _fetch_bayt_gulf():
    """
    Bayt.com — use their search API (not RSS which returns 403).
    """
    jobs = []
    seen = set()
    searches = [
        ("cybersecurity", "saudi-arabia"),
        ("information security", "uae"),
        ("soc analyst", "saudi-arabia"),
        ("security engineer", "uae"),
        ("cybersecurity", "egypt"),
    ]
    for keyword, country in searches:
        slug = keyword.replace(" ", "-")
        url = f"https://www.bayt.com/en/{country}/jobs/{slug}-jobs/"
        html = get_text(url, headers=HEADERS)
        if not html:
            continue
        import json as _json
        # Try to extract JSON-LD job postings
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data = _json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title = item.get("title", "").strip()
                    job_url = item.get("url", url)
                    org = item.get("hiringOrganization", {})
                    company = org.get("name", "").strip() if isinstance(org, dict) else ""
                    loc_obj = item.get("jobLocation", {})
                    if isinstance(loc_obj, dict):
                        addr = loc_obj.get("address", {})
                        location = addr.get("addressCountry", country.replace("-", " ").title()) if isinstance(addr, dict) else country
                    else:
                        location = country.replace("-", " ").title()
                    if not title or job_url in seen:
                        continue
                    seen.add(job_url)
                    jobs.append(Job(
                        title=title, company=company or "Bayt Employer",
                        location=location, url=job_url,
                        source="bayt", tags=["bayt", "gulf"],
                    ))
            except Exception:
                continue
    log.info("Bayt Gulf: " + str(len(jobs)) + " jobs")
    return jobs


# ─── Main entry point ─────────────────────────────────────────
def fetch_gov_gulf():
    """Fetch from confirmed-live Gulf sources only (parallel)."""
    fetchers = [
        _fetch_nca_ksa,
        _fetch_neom,
        _fetch_stc_ksa,
        _fetch_omantel,
        _fetch_g42,
        _fetch_tdra_uae,
        _fetch_etisalat_uae,
        _fetch_gulf_linkedin_companies,
        _fetch_bayt_gulf,
    ]
    all_jobs = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fn): fn.__name__ for fn in fetchers}
        try:
            for future in as_completed(futures, timeout=60):
                name = futures[future]
                try:
                    all_jobs.extend(future.result())
                except Exception as e:
                    log.warning("gov_gulf sub-fetcher " + name + " failed: " + str(e))
        except TimeoutError:
            done = sum(1 for f in futures if f.done())
            log.warning(f"gov_gulf: timeout after 60s — {done}/{len(futures)} fetchers completed")
    return all_jobs
