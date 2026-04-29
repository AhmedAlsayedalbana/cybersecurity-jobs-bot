"""
Egypt Sources — v27 FAST

KEY FIX: Added per-fetcher TIME BUDGET to prevent LinkedIn rate-limit hangs.
The old version had no budget → 63+ LinkedIn requests → bot hangs 30+ minutes.

Budgets:
  _fetch_linkedin_egypt_search   → 90s max
  _fetch_linkedin_eg_private     → 120s max
  _fetch_linkedin_eg_gov         → 60s max
  _fetch_linkedin_by_governorate → 60s max  (4 govs × 3 kw only)
  _fetch_wuzzuf                  → 30s max
"""

import logging
import re
import json
import time
import urllib.parse
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

JOBS_API = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

SEC_KW = [
    "cybersecurity", "cyber security", "information security", "network security",
    "soc analyst", "security engineer", "security analyst", "penetration",
    "pentest", "grc", "dfir", "cloud security", "devsecops", "malware",
    "forensic", "threat", "vulnerability", "appsec", "red team", "blue team",
    "security architect", "security manager", "security officer", "ciso",
    "infosec", "incident response", "security operations",
    "امن معلومات", "امن سيبراني", "اختبار اختراق",
]

def _is_sec(t): return any(k in t.lower() for k in SEC_KW)

def _li_jobs_from_html(html, location, source_tag):
    jobs = []
    job_ids   = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
    titles    = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', html)
    companies = re.findall(r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>\s*([^<]+)', html)
    for i, title in enumerate(titles):
        title = title.strip()
        if not title or not _is_sec(title):
            continue
        job_id  = job_ids[i] if i < len(job_ids) else ""
        company = companies[i].strip() if i < len(companies) else "Unknown"
        jobs.append(Job(
            title=title, company=company, location=location,
            url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else JOBS_API,
            source="linkedin", tags=["linkedin", "egypt", source_tag],
        ))
    return jobs


# ── 1. LinkedIn Egypt keyword search (trimmed to 8 high-value queries) ──
EGYPT_SEARCH_KEYWORDS = [
    # English — role-based
    "cybersecurity Egypt",
    "information security Egypt",
    "SOC analyst Egypt",
    "penetration tester Egypt",
    "security engineer Egypt",
    "GRC analyst Egypt",
    "network security engineer Egypt",
    "cloud security Egypt",
    "devsecops Egypt",
    "threat intelligence Egypt",
    "malware analyst Egypt",
    "security architect Egypt",
    "dfir Egypt",
    "appsec Egypt",
    "junior security Egypt",
    "security intern Egypt",
    "SIEM engineer Egypt",
    "vulnerability analyst Egypt",
    # Arabic — role-based
    "امن معلومات مصر",
    "امن سيبراني مصر",
    "محلل امن مصر",
    "مهندس امن مصر",
    "اختبار اختراق مصر",
    "حماية المعلومات",
]

def _fetch_linkedin_egypt_search():
    jobs = []
    seen = set()
    budget = 210  # v33: raised 150→210s
    t0 = time.time()
    for kw in EGYPT_SEARCH_KEYWORDS:
        if time.time() - t0 > budget:
            log.warning("egypt_alt/search: 90s budget hit — stopping early")
            break
        params = (
            f"?keywords={urllib.parse.quote(kw)}"
            "&location=Egypt&start=0&count=10&f_TPR=r604800&sortBy=DD"
        )
        html = get_text(JOBS_API + params, headers=_H)
        if not html:
            continue
        for j in _li_jobs_from_html(html, "Egypt", "search"):
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"LinkedIn Egypt Search: {len(jobs)} jobs")
    return jobs


# ── 2. LinkedIn Egypt private sector companies ───────────────
LINKEDIN_EG_PRIVATE = [
    ("CIB Egypt",                      "cib-egypt"),
    ("QNB Al Ahli",                    "qnb-alahli"),
    ("NBE",                            "national-bank-of-egypt"),
    ("Banque Misr",                    "banque-misr"),
    ("Banque du Caire",                "banque-du-caire"),
    ("HSBC Egypt",                     "hsbc"),
    ("Fawry",                          "fawry"),
    ("Paymob",                         "paymob"),
    ("Khazna",                         "khazna-data-associates"),
    ("ValU",                           "valu-egypt"),
    ("Vodafone Egypt",                 "vodafone-egypt"),
    ("Orange Egypt",                   "orange-egypt"),
    ("WE Telecom",                     "telecom-egypt"),
    ("Etisalat Misr",                  "etisalatmisr"),
    ("Raya IT",                        "raya-information-technology"),
    ("Link Development",               "link-development"),
    ("ITWORX",                         "itworx"),
    ("Instabug",                       "instabug"),
    ("Halan",                          "halan"),
    ("Synapse Analytics",              "synapse-analytics"),
    ("Siemens Egypt",                  "siemens"),
    ("IBM Egypt",                      "ibm"),
    ("Microsoft Egypt",                "microsoft"),
    ("Cisco Egypt",                    "cisco"),
    ("Accenture Egypt",                "accenture"),
    ("Deloitte Egypt",                 "deloitte"),
    ("KPMG Egypt",                     "kpmg"),
    ("PwC Egypt",                      "pwc"),
    ("EY Egypt",                       "ey"),
    ("Help AG Egypt",                  "help-ag"),
    ("Xceed",                          "xceed"),
]

def _fetch_linkedin_eg_private():
    jobs = []
    seen = set()
    budget = 240  # v33: raised 180→240s
    t0 = time.time()
    for company_name, slug in LINKEDIN_EG_PRIVATE:
        if time.time() - t0 > budget:
            log.warning("egypt_alt/private: 120s budget hit — stopping early")
            break
        url = f"{JOBS_API}?keywords=security&f_C={slug}&start=0&count=10"
        html = get_text(url, headers=_H)
        if not html:
            continue
        for j in _li_jobs_from_html(html, "Egypt", "private-sector"):
            j.company = company_name
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"LinkedIn Egypt Private: {len(jobs)} jobs")
    return jobs


# ── 3. LinkedIn Egypt government & public sector ─────────────
LINKEDIN_EG_GOV = [
    ("MCIT Egypt",            "mcit-egypt"),
    ("NTRA Egypt",            "national-telecom-regulatory-authority"),
    ("EG-CERT",               "eg-cert"),
    ("Central Bank of Egypt", "central-bank-of-egypt"),
    ("ITI Egypt",             "information-technology-institute"),
    ("ITIDA",                 "itida"),
]

def _fetch_linkedin_eg_gov():
    jobs = []
    seen = set()
    budget = 120  # v33: raised 90→120s (governorate)
    t0 = time.time()
    for company_name, slug in LINKEDIN_EG_GOV:
        if time.time() - t0 > budget:
            log.warning("egypt_alt/gov: 60s budget hit — stopping early")
            break
        url = f"{JOBS_API}?keywords=security&f_C={slug}&start=0&count=10"
        html = get_text(url, headers=_H)
        if not html:
            continue
        for j in _li_jobs_from_html(html, "Egypt", "public-sector"):
            j.company = company_name
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"LinkedIn Egypt Gov: {len(jobs)} jobs")
    return jobs


# ── 4. LinkedIn by Egyptian Governorates (trimmed 4 × 3 = 12 requests) ──
TOP_GOVERNORATES = [
    "Cairo, Egypt",
    "New Cairo, Egypt",
    "New Administrative Capital, Egypt",
    "Giza, Egypt",
]

GOVERNORATE_KEYWORDS = [
    "cybersecurity",
    "information security",
    "SOC analyst",
]

def _fetch_linkedin_by_governorate():
    jobs = []
    seen = set()
    budget = 90  # v33: raised 60→90s (by_governorate)
    t0 = time.time()
    for gov in TOP_GOVERNORATES:
        for kw in GOVERNORATE_KEYWORDS:
            if time.time() - t0 > budget:
                log.warning("egypt_alt/governorate: 90s budget hit — stopping early")
                break
            params = (
                f"?keywords={urllib.parse.quote(kw)}"
                f"&location={urllib.parse.quote(gov)}"
                "&start=0&count=5&f_TPR=r86400"
            )
            html = get_text(JOBS_API + params, headers=_H)
            if not html:
                continue
            for j in _li_jobs_from_html(html, gov, gov.split(",")[0].lower()):
                if j.url not in seen:
                    seen.add(j.url)
                    jobs.append(j)
    log.info(f"LinkedIn Egypt Governorates: {len(jobs)} jobs")
    return jobs


# ── 5. Wuzzuf HTML scrape ────────────────────────────────────
WUZZUF_QUERIES = [
    "cybersecurity", "information security", "SOC analyst",
    "penetration tester", "security engineer", "GRC", "امن معلومات",
]

def _fetch_wuzzuf():
    jobs = []
    seen = set()
    budget = 30
    t0 = time.time()
    for q in WUZZUF_QUERIES:
        if time.time() - t0 > budget:
            log.warning("egypt_alt/wuzzuf: 30s budget hit — stopping early")
            break
        url  = f"https://wuzzuf.net/search/jobs/?q={urllib.parse.quote(q)}&a=hpb"
        html = get_text(url, headers=_H)
        if not html:
            continue
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            try:
                data  = json.loads(m.group(1))
                items = (data.get("props", {}).get("pageProps", {})
                             .get("jobList", {}).get("jobs", []))
                for item in items:
                    title   = item.get("title", "").strip()
                    job_url = "https://wuzzuf.net/jobs/p/" + item.get("slug", "")
                    company = item.get("company", {}).get("name", "") if isinstance(item.get("company"), dict) else ""
                    if not title or job_url in seen or not _is_sec(title):
                        continue
                    seen.add(job_url)
                    jobs.append(Job(
                        title=title, company=company or "Wuzzuf",
                        location="Egypt", url=job_url,
                        source="wuzzuf", tags=["wuzzuf", "egypt"],
                    ))
            except Exception:
                pass
    log.info(f"Wuzzuf Egypt: {len(jobs)} jobs")
    return jobs


def fetch_egypt_alt() -> list:
    """Fetch from Egypt alternative sources. Each sub-fetcher has a time budget."""
    all_jobs = []
    for fn in [
        _fetch_linkedin_egypt_search,    # 90s budget
        _fetch_linkedin_eg_private,      # 120s budget
        _fetch_linkedin_eg_gov,          # 60s budget
        _fetch_linkedin_by_governorate,  # 60s budget (trimmed)
        _fetch_wuzzuf,                   # 30s budget
    ]:
        try:
            all_jobs.extend(fn())
        except Exception as e:
            log.warning(f"egypt_alt: {fn.__name__} failed: {e}")
    return all_jobs
