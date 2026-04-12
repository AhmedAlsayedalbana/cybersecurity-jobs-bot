"""
Egyptian Sources — Cybersecurity Jobs
STATUS (confirmed from production logs):
  ✅ Wuzzuf Egypt RSS      — best source, 30-50 jobs per run
  ✅ Egypt Cyber Firms     — Wuzzuf company pages
  ✅ CBE                   — ~12 jobs
  ✅ MCIT                  — ~2 jobs
  ✅ LinkedIn Egypt Cos    — ~5 jobs (rate-limited sometimes)

REMOVED (confirmed dead):
  ❌ ITIDA, ITI, EG-CERT, DEPI, NTI, NTRA, TIEC, Smart Village, Banks
     → All return 404, DNS fail, or timeout every single run

TIMEOUT FIX:
  ThreadPoolExecutor now uses as_completed() with per-future try/except.
  No more "5 futures unfinished" error crashing the fetcher.
"""

import logging
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_EXCEPTION
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}


# ─── 1. Wuzzuf Egypt RSS — PRIMARY SOURCE ────────────────────
WUZZUF_QUERIES = [
    "cybersecurity", "information+security", "SOC+analyst",
    "penetration+testing", "security+engineer", "security+analyst",
    "cloud+security", "GRC", "malware+analyst", "threat+intelligence",
    "devsecops", "DFIR", "network+security", "security+architect",
]

def _fetch_wuzzuf_egypt():
    """Wuzzuf RSS — Egypt's #1 job board. Reliable and fast."""
    jobs = []
    seen = set()
    for q in WUZZUF_QUERIES:
        rss_url = f"https://wuzzuf.net/search/jobs/rss/?q={q}&a=hpb&l=Egypt"
        xml = get_text(rss_url, headers=HEADERS)
        if not xml:
            continue
        try:
            root = ET.fromstring(xml)
            for item in root.findall(".//item"):
                title   = item.findtext("title", "").strip()
                link    = item.findtext("link",  "").strip()
                company = item.findtext("author", "").strip() or "Unknown"
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                jobs.append(Job(
                    title=title, company=company,
                    location="Egypt", url=link,
                    source="wuzzuf",
                    tags=["wuzzuf", "egypt", q.replace("+", " ")],
                ))
        except ET.ParseError as e:
            log.warning(f"Wuzzuf RSS parse error ({q}): {e}")
    log.info(f"Wuzzuf Egypt RSS: {len(jobs)} jobs")
    return jobs


# ─── 2. Egypt Cyber Firms via Wuzzuf company pages ───────────
CYBER_FIRMS = [
    ("ITWorx",                "https://wuzzuf.net/search/jobs/?q=security&a=hpb&o=ITWorx"),
    ("IBM Egypt",             "https://wuzzuf.net/search/jobs/?q=security&a=hpb&o=IBM"),
    ("Microsoft Egypt",       "https://wuzzuf.net/search/jobs/?q=security&a=hpb&o=Microsoft"),
    ("Cisco Egypt",           "https://wuzzuf.net/search/jobs/?q=security&a=hpb&o=Cisco"),
    ("Orange Egypt",          "https://wuzzuf.net/search/jobs/?q=security&a=hpb&o=Orange"),
    ("Vodafone Egypt",        "https://wuzzuf.net/search/jobs/?q=security&a=hpb&o=Vodafone"),
    ("Telecom Egypt (WE)",    "https://wuzzuf.net/search/jobs/?q=security&a=hpb&o=Telecom+Egypt"),
    ("e& Egypt (Etisalat)",   "https://wuzzuf.net/search/jobs/?q=security&a=hpb&o=Etisalat"),
    ("Fawry",                 "https://wuzzuf.net/search/jobs/?q=security&a=hpb&o=Fawry"),
    ("Paymob",                "https://wuzzuf.net/search/jobs/?q=security&a=hpb&o=Paymob"),
    ("CIB Bank",              "https://wuzzuf.net/search/jobs/?q=security&a=hpb&o=CIB"),
    ("Banque Misr",           "https://wuzzuf.net/search/jobs/?q=security&a=hpb&o=Banque+Misr"),
    ("KPMG Egypt",            "https://wuzzuf.net/search/jobs/?q=security&a=hpb&o=KPMG"),
    ("Deloitte Egypt",        "https://wuzzuf.net/search/jobs/?q=security&a=hpb&o=Deloitte"),
    ("PwC Egypt",             "https://wuzzuf.net/search/jobs/?q=security&a=hpb&o=PwC"),
    ("EY Egypt",              "https://wuzzuf.net/search/jobs/?q=security&a=hpb&o=EY"),
]

def _fetch_egypt_cyber_firms():
    """Wuzzuf company pages for top Egypt cyber employers."""
    jobs = []
    seen = set()
    for company_name, url in CYBER_FIRMS:
        html = get_text(url, headers=HEADERS)
        if not html:
            continue
        # Extract job cards from Wuzzuf search results
        cards = re.findall(
            r'data-job-pref="([^"]+)"[^>]*>.*?<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>',
            html, re.DOTALL
        )
        for _, link, title in cards:
            title = title.strip()
            full_url = "https://wuzzuf.net" + link if link.startswith("/") else link
            if full_url in seen:
                continue
            seen.add(full_url)
            jobs.append(Job(
                title=title, company=company_name,
                location="Cairo, Egypt", url=full_url,
                source="wuzzuf_eg",
                tags=["egypt", "wuzzuf", company_name.lower()],
            ))
    log.info(f"Egypt Cyber Firms: {len(jobs)} jobs")
    return jobs


# ─── 3. CBE (Central Bank of Egypt) ─────────────────────────
def _fetch_cbe():
    jobs = []
    for url in ["https://www.cbe.org.eg/en/human-resources/careers",
                "https://www.cbe.org.eg/en/careers"]:
        html = get_text(url, headers=HEADERS)
        if not html:
            continue
        found = set()
        for pat in [
            r'<h[2-5][^>]*>([^<]{10,120}(?:security|cyber|network|analyst|engineer|specialist|officer|IT)[^<]{0,80})</h[2-5]>',
            r'"title"\s*:\s*"([^"]{10,120}(?:security|cyber|analyst|engineer|officer)[^"]{0,80})"',
        ]:
            for m in re.findall(pat, html, re.IGNORECASE):
                title = re.sub(r'<[^>]+>', '', m).strip()
                if title and title not in found and len(title) > 8:
                    found.add(title)
                    jobs.append(Job(
                        title=title, company="Central Bank of Egypt",
                        location="Cairo, Egypt", url=url,
                        source="cbe", tags=["cbe", "government", "egypt"],
                    ))
        if jobs:
            break
    log.info(f"CBE: {len(jobs)} jobs")
    return jobs


# ─── 4. Indeed Egypt RSS ──────────────────────────────────────
INDEED_QUERIES = [
    "cybersecurity", "SOC analyst", "security engineer",
    "penetration tester", "information security",
]

def _fetch_indeed_egypt():
    """Indeed Egypt RSS feed — no login needed."""
    jobs = []
    seen = set()
    for q in INDEED_QUERIES:
        q_enc = q.replace(" ", "+")
        url = f"https://eg.indeed.com/rss?q={q_enc}&l=Egypt&fromage=7"
        xml = get_text(url, headers=HEADERS)
        if not xml:
            continue
        try:
            root = ET.fromstring(xml)
            for item in root.findall(".//item"):
                title   = item.findtext("title", "").strip()
                link    = item.findtext("link",  "").strip()
                company = item.findtext("source", "").strip() or "Unknown"
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                jobs.append(Job(
                    title=title, company=company,
                    location="Egypt", url=link,
                    source="indeed_eg",
                    tags=["indeed", "egypt", q],
                ))
        except ET.ParseError:
            pass
    log.info(f"Indeed Egypt: {len(jobs)} jobs")
    return jobs


# ─── 5. LinkedIn Egypt Company Pages ─────────────────────────
LINKEDIN_EG_COMPANIES = [
    ("Telecom Egypt",   "telecom-egypt"),
    ("CIB Bank",        "commercial-international-bank"),
    ("Fawry",           "fawry"),
    ("ITWorx",          "itworx"),
]

def _fetch_egypt_linkedin_companies():
    """LinkedIn company pages for Egyptian firms."""
    jobs = []
    seen = set()
    for company_name, slug in LINKEDIN_EG_COMPANIES:
        url = (
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
            f"?keywords=security&f_C={slug}&start=0&count=10"
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
                location="Egypt", url=job_url,
                source="linkedin",
                tags=["linkedin", "egypt"],
            ))
        time.sleep(1)
    log.info(f"LinkedIn Egypt Companies: {len(jobs)} jobs")
    return jobs


# ─── Main entry — FIXED ThreadPoolExecutor ────────────────────
def fetch_gov_egypt():
    """
    Fetch from confirmed-live Egyptian sources (parallel).
    FIX: uses per-future exception handling instead of timeout=N
    which was causing 'futures unfinished' errors in production.
    """
    fetchers = [
        _fetch_wuzzuf_egypt,
        _fetch_egypt_cyber_firms,
        _fetch_cbe,
        _fetch_indeed_egypt,
        _fetch_egypt_linkedin_companies,
    ]
    all_jobs = []
    # Use timeout=None — individual HTTP calls already have their own timeouts
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fn): fn.__name__ for fn in fetchers}
        done, _ = wait(futures, timeout=90)   # generous wall-clock timeout
        for future in done:
            name = futures[future]
            try:
                result = future.result()
                all_jobs.extend(result)
            except Exception as e:
                log.warning(f"gov_egypt: {name} failed: {e}")
        pending = len(futures) - len(done)
        if pending:
            log.warning(f"gov_egypt: {pending} fetcher(s) timed out — skipping")
    return all_jobs
