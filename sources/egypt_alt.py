"""
Egypt Sources — v26

CONFIRMED WORKING:
  ✅ LinkedIn Egypt keyword search
  ✅ LinkedIn Egypt private sector companies (expanded)
  ✅ LinkedIn Egypt by governorate (expanded keywords)
  ✅ LinkedIn Egypt public sector & government
  ✅ Wuzzuf HTML scrape

REMOVED (dead):
  ❌ Bayt RSS (403), Naukrigulf Egypt (timeout), Forasna (404), Tanqeeb (403)
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
    "أمن معلومات", "أمن سيبراني", "اختبار اختراق",
]

def _is_sec(t): return any(k in t.lower() for k in SEC_KW)

def _li_jobs_from_html(html, location, source_tag):
    """Extract jobs from LinkedIn guest search HTML."""
    jobs = []
    job_ids  = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
    titles   = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', html)
    companies= re.findall(r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>\s*([^<]+)', html)
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


# ── 1. LinkedIn Egypt — keyword search (broad) ───────────────
EGYPT_SEARCH_KEYWORDS = [
    "cybersecurity", "information security", "SOC analyst",
    "penetration tester", "security engineer", "network security",
    "cloud security", "devsecops", "GRC analyst", "malware analyst",
    "security architect", "CISO", "incident response",
    "أمن معلومات", "أمن سيبراني",
]

def _fetch_linkedin_egypt_search():
    jobs = []
    seen = set()
    for kw in EGYPT_SEARCH_KEYWORDS:
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
        time.sleep(0.5)
    log.info(f"LinkedIn Egypt Search: {len(jobs)} jobs")
    return jobs


# ── 2. LinkedIn Egypt — private sector companies (expanded) ──
LINKEDIN_EG_PRIVATE = [
    # Banks & Finance
    ("CIB Egypt",                      "cib-egypt"),
    ("QNB Al Ahli",                    "qnb-alahli"),
    ("NBE",                            "national-bank-of-egypt"),
    ("Banque Misr",                    "banque-misr"),
    ("Banque du Caire",                "banque-du-caire"),
    ("HSBC Egypt",                     "hsbc"),
    ("Arab African International Bank","arab-african-international-bank"),
    ("Abu Dhabi Islamic Bank Egypt",   "adib-egypt"),
    ("Fawry",                          "fawry"),
    ("Paymob",                         "paymob"),
    ("Khazna",                         "khazna-data-associates"),
    ("ValU",                           "valu-egypt"),
    # Telecom
    ("Vodafone Egypt",                 "vodafone-egypt"),
    ("Orange Egypt",                   "orange-egypt"),
    ("WE Telecom",                     "telecom-egypt"),
    ("Etisalat Misr",                  "etisalatmisr"),
    # Tech Companies
    ("Raya IT",                        "raya-information-technology"),
    ("Link Development",               "link-development"),
    ("ITWORX",                         "itworx"),
    ("Instabug",                       "instabug"),
    ("Halan",                          "halan"),
    ("Synapse Analytics",              "synapse-analytics"),
    ("Dsquares",                       "dsquares"),
    ("SilverKey Technologies",         "silverkey-technologies"),
    ("Siemens Egypt",                  "siemens"),
    ("IBM Egypt",                      "ibm"),
    ("Microsoft Egypt",                "microsoft"),
    ("Dell Egypt",                     "dell-technologies"),
    ("Cisco Egypt",                    "cisco"),
    ("HP Egypt",                       "hp"),
    # Big 4 consulting
    ("Deloitte Egypt",                 "deloitte"),
    ("KPMG Egypt",                     "kpmg"),
    ("PwC Egypt",                      "pwc"),
    ("EY Egypt",                       "ey"),
    ("Accenture Egypt",                "accenture"),
    # Cybersecurity specific
    ("Help AG Egypt",                  "help-ag"),
    ("NCC Group Egypt",                "ncc-group"),
    ("Xceed",                          "xceed"),
]

def _fetch_linkedin_eg_private():
    jobs = []
    seen = set()
    for company_name, slug in LINKEDIN_EG_PRIVATE:
        url = f"{JOBS_API}?keywords=security&f_C={slug}&start=0&count=10"
        html = get_text(url, headers=_H)
        if not html:
            time.sleep(0.3)
            continue
        for j in _li_jobs_from_html(html, "Egypt", "private-sector"):
            j.company = company_name
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
        time.sleep(0.6)
    log.info(f"LinkedIn Egypt Private: {len(jobs)} jobs")
    return jobs


# ── 3. LinkedIn Egypt — government & public sector ───────────
LINKEDIN_EG_GOV = [
    ("MCIT Egypt",              "mcit-egypt"),
    ("NTRA Egypt",              "national-telecom-regulatory-authority"),
    ("EG-CERT",                 "eg-cert"),
    ("Central Bank of Egypt",   "central-bank-of-egypt"),
    ("ITI Egypt",               "information-technology-institute"),
    ("Egyptian Armed Forces",   "egyptian-armed-forces"),
    ("Ministry of Interior EG", "ministry-of-interior-egypt"),
    ("ISOC Egypt",              "internet-society"),
    ("ITIDA",                   "itida"),
]

def _fetch_linkedin_eg_gov():
    jobs = []
    seen = set()
    for company_name, slug in LINKEDIN_EG_GOV:
        url = f"{JOBS_API}?keywords=security&f_C={slug}&start=0&count=10"
        html = get_text(url, headers=_H)
        if not html:
            time.sleep(0.3)
            continue
        for j in _li_jobs_from_html(html, "Egypt", "public-sector"):
            j.company = company_name
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
        time.sleep(0.6)
    log.info(f"LinkedIn Egypt Gov: {len(jobs)} jobs")
    return jobs


# ── 4. LinkedIn by Egyptian Governorates (expanded keywords) ──
TECH_HUB_GOVERNORATES = [
    "Cairo, Egypt",
    "Alexandria, Egypt",
    "Giza, Egypt",
    "New Cairo, Egypt",
    "6th of October City, Egypt",
    "New Administrative Capital, Egypt",
    "Qalyubia, Egypt",
    "Mansoura, Egypt",
    "Tanta, Egypt",
]

GOVERNORATE_KEYWORDS = [
    "cybersecurity", "information security", "security analyst",
    "SOC analyst", "network security", "penetration tester",
    "أمن معلومات",
]

def _fetch_linkedin_by_governorate():
    jobs = []
    seen = set()
    for gov in TECH_HUB_GOVERNORATES:
        for kw in GOVERNORATE_KEYWORDS:
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
            time.sleep(0.4)
    log.info(f"LinkedIn Egypt Governorates: {len(jobs)} jobs")
    return jobs


# ── 5. Wuzzuf HTML scrape ────────────────────────────────────
WUZZUF_QUERIES = [
    "cybersecurity", "information security", "SOC analyst",
    "penetration tester", "security engineer", "network security",
    "GRC", "CISO", "devsecops", "cloud security", "أمن معلومات",
]

def _fetch_wuzzuf():
    jobs = []
    seen = set()
    for q in WUZZUF_QUERIES:
        url  = f"https://wuzzuf.net/search/jobs/?q={urllib.parse.quote(q)}&a=hpb"
        html = get_text(url, headers=_H)
        if not html:
            continue
        # Try Next.js JSON blob
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
        time.sleep(0.5)
    log.info(f"Wuzzuf Egypt: {len(jobs)} jobs")
    return jobs


def fetch_egypt_alt() -> list:
    all_jobs = []
    for fn in [
        _fetch_linkedin_egypt_search,
        _fetch_linkedin_eg_private,
        _fetch_linkedin_eg_gov,
        _fetch_linkedin_by_governorate,
        _fetch_wuzzuf,
    ]:
        try:
            all_jobs.extend(fn())
        except Exception as e:
            log.warning(f"egypt_alt: {fn.__name__} failed: {e}")
    return all_jobs
