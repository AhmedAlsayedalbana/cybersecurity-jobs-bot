"""
Gulf Sources — Cybersecurity Jobs
CONFIRMED LIVE (from production logs):
  ✅ STC KSA          — 4 jobs
  ✅ Omantel          — 10 jobs
  ✅ TDRA UAE         — 15 jobs
  ✅ LinkedIn Gulf    — 10 jobs
  ✅ Etisalat UAE     — 1 job
  ✅ Bayt JSON-LD     — added
  ✅ Gulf ATS (Workday/Greenhouse) — new

REMOVED (confirmed dead every run):
  ❌ NCA KSA (Greenhouse 404 all slugs)
  ❌ NEOM (Greenhouse 404 — "neom" and "neomcompany" both 404)
  ❌ G42 (Greenhouse 404)
  ❌ Bayt RSS (403 Forbidden)
  ❌ CITC/SDAIA/QCERT/Ooredoo/Zain (unreachable)

TIMEOUT FIX:
  Uses wait() + per-future exception instead of as_completed(timeout=N).
"""

import logging
import re
import time
import xml.etree.ElementTree as ET
import json as _json
from concurrent.futures import ThreadPoolExecutor, wait
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


# ─── 1. STC KSA — confirmed working ──────────────────────────
def _fetch_stc_ksa():
    jobs = []
    for url in [
        "https://www.stc.com.sa/en/career/current-openings",
        "https://careers.stc.com.sa/",
    ]:
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
    log.info(f"STC KSA: {len(jobs)} jobs")
    return jobs


# ─── 2. Omantel — confirmed working ──────────────────────────
def _fetch_omantel():
    jobs = []
    for url in [
        "https://www.omantel.om/en/about-omantel/careers",
        "https://careers.omantel.om/",
    ]:
        html = get_text(url, headers=HEADERS)
        if not html:
            continue
        found = set()
        # JSON-LD first
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
                    if title and title not in found:
                        found.add(title)
                        jobs.append(Job(
                            title=title, company="Omantel",
                            location="Oman", url=job_url,
                            source="omantel", tags=["omantel", "oman", "gulf"],
                        ))
            except Exception:
                continue
        # Heading-based fallback
        if not jobs:
            for m in re.findall(
                r'<h[2-5][^>]*>([^<]{10,120}(?:security|cyber|network|IT|analyst|engineer)[^<]{0,80})</h[2-5]>',
                html, re.IGNORECASE
            ):
                title = re.sub(r'<[^>]+>', '', m).strip()
                if title and title not in found:
                    found.add(title)
                    jobs.append(Job(
                        title=title, company="Omantel",
                        location="Oman", url=url,
                        source="omantel", tags=["omantel", "oman"],
                    ))
        if jobs:
            break
    log.info(f"Omantel: {len(jobs)} jobs")
    return jobs


# ─── 3. TDRA UAE — confirmed working ─────────────────────────
def _fetch_tdra_uae():
    jobs = []
    for url in [
        "https://tdra.gov.ae/en/about/careers",
        "https://www.tra.gov.ae/en/content/careers",
    ]:
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
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title = item.get("title", "").strip()
                    job_url = item.get("url", url)
                    if title and title not in found:
                        found.add(title)
                        jobs.append(Job(
                            title=title, company="TDRA UAE",
                            location="UAE", url=job_url,
                            source="tdra_uae", tags=["tdra", "uae", "government"],
                        ))
            except Exception:
                continue
        if not jobs:
            for m in re.findall(
                r'<h[2-5][^>]*>([^<]{10,120}(?:security|cyber|analyst|engineer|IT|network)[^<]{0,80})</h[2-5]>',
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


# ─── 4. Etisalat (e&) UAE — confirmed working ────────────────
def _fetch_etisalat_uae():
    jobs = []
    urls = [
        "https://www.eand.com/en/careers/current-opportunities.html",
        "https://careers.eand.com/",
        "https://www.etisalat.ae/en/careers/",
    ]
    for url in urls:
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
                    source="etisalat_uae", tags=["etisalat", "uae", "telecom"],
                ))
        if jobs:
            break
    log.info(f"Etisalat UAE: {len(jobs)} jobs")
    return jobs


# ─── 5. Gulf LinkedIn Company Pages ──────────────────────────
LINKEDIN_GULF_COMPANIES = [
    ("Saudi Aramco",    "saudi-aramco"),
    ("STC KSA",         "stc"),
    ("Zain KSA",        "zain-ksa"),
    ("du UAE",          "du"),
    ("Etisalat UAE",    "etisalat"),
]

def _fetch_gulf_linkedin_companies():
    jobs = []
    seen = set()
    for company_name, slug in LINKEDIN_GULF_COMPANIES:
        url = (
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
            f"?keywords=cybersecurity&f_C={slug}&start=0&count=10"
        )
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


# ─── 6. Bayt — JSON-LD extraction (bypasses 403 on RSS) ──────
BAYT_SEARCHES = [
    ("cybersecurity", "saudi-arabia"),
    ("information-security", "uae"),
    ("soc-analyst", "saudi-arabia"),
    ("security-engineer", "uae"),
    ("cybersecurity", "egypt"),
    ("penetration-tester", "saudi-arabia"),
]

def _fetch_bayt_gulf():
    jobs = []
    seen = set()
    for slug, country in BAYT_SEARCHES:
        url = f"https://www.bayt.com/en/{country}/jobs/{slug}-jobs/"
        html = get_text(url, headers=HEADERS)
        if not html:
            continue
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
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", url)
                    org     = item.get("hiringOrganization", {})
                    company = org.get("name", "").strip() if isinstance(org, dict) else ""
                    loc_obj = item.get("jobLocation", {})
                    if isinstance(loc_obj, dict):
                        addr     = loc_obj.get("address", {})
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
    log.info(f"Bayt Gulf: {len(jobs)} jobs")
    return jobs


# ─── 7. Gulf Indeed RSS ───────────────────────────────────────
GULF_INDEED_SEARCHES = [
    ("cybersecurity", "Saudi Arabia"),
    ("security engineer", "UAE"),
    ("SOC analyst", "Saudi Arabia"),
    ("information security", "UAE"),
]

def _fetch_gulf_indeed():
    jobs = []
    seen = set()
    for q, country in GULF_INDEED_SEARCHES:
        q_enc   = q.replace(" ", "+")
        loc_enc = country.replace(" ", "+")
        url = f"https://www.indeed.com/rss?q={q_enc}&l={loc_enc}&fromage=7"
        xml = get_text(url, headers=HEADERS)
        if not xml:
            continue
        try:
            root = ET.fromstring(xml)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                comp  = item.findtext("source", "").strip() or "Unknown"
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                jobs.append(Job(
                    title=title, company=comp,
                    location=country, url=link,
                    source="indeed_gulf",
                    tags=["indeed", "gulf", country.lower()],
                ))
        except ET.ParseError:
            pass
    log.info(f"Gulf Indeed: {len(jobs)} jobs")
    return jobs


# ─── Main entry — FIXED ThreadPoolExecutor ────────────────────
def fetch_gov_gulf():
    """
    Fetch from confirmed-live Gulf sources (parallel).
    FIX: wait() with timeout instead of as_completed(timeout=N)
         to avoid 'futures unfinished' crash.
    """
    fetchers = [
        _fetch_stc_ksa,
        _fetch_omantel,
        _fetch_tdra_uae,
        _fetch_etisalat_uae,
        _fetch_gulf_linkedin_companies,
        _fetch_bayt_gulf,
        _fetch_gulf_indeed,
    ]
    all_jobs = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fn): fn.__name__ for fn in fetchers}
        done, _ = wait(futures, timeout=90)
        for future in done:
            name = futures[future]
            try:
                all_jobs.extend(future.result())
            except Exception as e:
                log.warning(f"gov_gulf: {name} failed: {e}")
        pending = len(futures) - len(done)
        if pending:
            log.warning(f"gov_gulf: {pending} fetcher(s) timed out — skipping")
    return all_jobs
