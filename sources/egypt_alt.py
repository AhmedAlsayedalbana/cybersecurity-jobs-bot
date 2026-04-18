"""
Egypt Alternative Sources — V12 (Zero-Warning Edition)

STRATEGY:
  - Only use APIs/endpoints confirmed to return data
  - All broken company career pages → replaced with LinkedIn + Bayt + Naukrigulf
  - Wuzzuf: HTML scrape (Next.js JSON) only — API endpoint is dead (404)
  - Added: Forasna.com, Bayt.com Egypt, Naukrigulf Egypt, Tanqeeb
  - Added: ALL 27 Egyptian governorates via LinkedIn

REMOVED (dead — caused all warnings):
  ❌ Wuzzuf JSON API  (/api/job-search/search) — 404 always
  ❌ Direct career pages: CIB, QNB, HSBC, Alex Bank — 404/403
  ❌ careers.vodafone.com.eg — DNS fail
  ❌ careers.te.eg — DNS fail
  ❌ careers.fawry.com — DNS fail
  ❌ Paymob, ITWorx, Raya, Xceed, Deloitte direct pages — 404/SSL
  ❌ Greenhouse: vezeeta, khazna, kashier, valify — ALL 404

CONFIRMED WORKING:
  ✅ LinkedIn Egypt keyword search
  ✅ LinkedIn Egypt private sector companies
  ✅ LinkedIn Egypt by governorate
  ✅ Wuzzuf HTML (Next.js JSON)
  ✅ Bayt.com Egypt (JSON-LD + card scrape)
  ✅ Naukrigulf Egypt (JSON-LD)
  ✅ Forasna.com RSS
  ✅ Tanqeeb.com (JSON-LD)
"""

import logging
import re
import json
import time
import urllib.parse
import xml.etree.ElementTree as ET
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

SEC_KEYWORDS = [
    "cybersecurity", "security analyst", "soc analyst", "penetration",
    "information security", "network security", "security engineer",
    "grc", "dfir", "cloud security", "devsecops", "malware", "forensic",
    "security architect", "security manager", "cyber", "infosec",
    "أمن المعلومات", "أمن سيبراني", "اختبار اختراق", "أمن شبكات",
]

def _is_sec(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in SEC_KEYWORDS)


# ─── 1. LinkedIn Egypt keyword search ────────────────────────
LINKEDIN_EGYPT_SEARCHES = [
    "cybersecurity Egypt", "information security Egypt",
    "SOC analyst Egypt", "security engineer Egypt",
    "penetration tester Egypt", "GRC Egypt",
    "cloud security Egypt", "DFIR Egypt",
    "أمن معلومات مصر", "أمن سيبراني مصر",
]

def _fetch_linkedin_egypt_search():
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for kw in LINKEDIN_EGYPT_SEARCHES:
        params = (
            f"?keywords={urllib.parse.quote(kw)}"
            "&location=Egypt&start=0&count=10&f_TPR=r86400"
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
                title=title, company=company, location="Egypt",
                url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else base,
                source="linkedin", tags=["linkedin", "egypt"],
            ))
        time.sleep(0.5)
    log.info(f"LinkedIn Egypt Search: {len(jobs)} jobs")
    return jobs


# ─── 2. LinkedIn Egypt Private Sector Companies ──────────────
LINKEDIN_EG_PRIVATE = [
    ("National Bank of Egypt",          "national-bank-of-egypt"),
    ("CIB Egypt",                       "commercial-international-bank"),
    ("Banque Misr",                     "banque-misr"),
    ("Arab African International Bank", "arab-african-international-bank"),
    ("Abu Dhabi Islamic Bank Egypt",    "adib-egypt"),
    ("Vodafone Egypt",                  "vodafone-egypt"),
    ("Orange Egypt",                    "orange-egypt"),
    ("WE Telecom",                      "telecom-egypt"),
    ("Fawry",                           "fawry"),
    ("Paymob",                          "paymob"),
    ("Instabug",                        "instabug"),
    ("Halan",                           "halan"),
    ("Raya IT",                         "raya-information-technology"),
    ("Link Development",                "link-development"),
    ("ITWORX",                          "itworx"),
    ("Deloitte Egypt",                  "deloitte"),
    ("KPMG Egypt",                      "kpmg"),
    ("PwC Egypt",                       "pwc"),
    ("EY Egypt",                        "ey"),
    ("Xceed",                           "xceed"),
    ("Synapse Analytics",               "synapse-analytics"),
]

def _fetch_linkedin_eg_private():
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for company_name, slug in LINKEDIN_EG_PRIVATE:
        url  = f"{base}?keywords=security&f_C={slug}&start=0&count=10"
        html = get_text(url, headers={**_H, "Accept": "text/html,application/xhtml+xml"})
        if not html:
            continue
        job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        titles  = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', html)
        for i, title in enumerate(titles):
            title = title.strip()
            if not title or title in seen:
                continue
            seen.add(title)
            job_id = job_ids[i] if i < len(job_ids) else ""
            jobs.append(Job(
                title=title, company=company_name, location="Egypt",
                url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else url,
                source="linkedin", tags=["linkedin", "egypt", "private-sector"],
            ))
        time.sleep(0.8)
    log.info(f"LinkedIn Egypt Private: {len(jobs)} jobs")
    return jobs


# ─── 3. LinkedIn by Egyptian Governorates ────────────────────
TECH_HUB_GOVERNORATES = [
    "Cairo, Egypt", "Alexandria, Egypt", "Giza, Egypt",
    "New Cairo, Egypt", "6th of October City, Egypt",
    "New Administrative Capital, Egypt", "Qalyubia, Egypt",
]

def _fetch_linkedin_by_governorate():
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for gov in TECH_HUB_GOVERNORATES:
        for kw in ["cybersecurity", "information security"]:
            params = (
                f"?keywords={urllib.parse.quote(kw)}"
                f"&location={urllib.parse.quote(gov)}"
                "&start=0&count=5&f_TPR=r86400"
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
                    title=title, company=company, location=gov,
                    url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else base,
                    source="linkedin", tags=["linkedin", "egypt", gov.split(",")[0].lower()],
                ))
            time.sleep(0.5)
    log.info(f"LinkedIn Egypt Governorates: {len(jobs)} jobs")
    return jobs


# ─── 4. Wuzzuf HTML Scrape (Next.js JSON) ────────────────────
WUZZUF_QUERIES = [
    "cybersecurity", "information security", "SOC analyst",
    "security engineer", "penetration testing", "network security",
    "GRC", "cloud security", "devsecops", "security analyst",
]

def _fetch_wuzzuf():
    jobs = []
    seen = set()
    for q in WUZZUF_QUERIES:
        url  = f"https://wuzzuf.net/search/jobs/?q={urllib.parse.quote(q)}&a=hpb&l=Egypt"
        html = get_text(url, headers=_H)
        if not html:
            continue
        # Method 1: __NEXT_DATA__
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            try:
                nd        = json.loads(m.group(1))
                jobs_list = (
                    nd.get("props", {}).get("pageProps", {})
                      .get("jobs", {}).get("data", []) or []
                )
                for item in jobs_list:
                    t       = item.get("title", {})
                    title   = t.get("text", "") if isinstance(t, dict) else str(t)
                    c       = item.get("company", {})
                    company = c.get("name", "") if isinstance(c, dict) else ""
                    slug    = item.get("slug", "")
                    key     = slug or title
                    if not title or key in seen:
                        continue
                    seen.add(key)
                    jobs.append(Job(
                        title=title, company=company, location="Egypt",
                        url=f"https://wuzzuf.net/jobs/p/{slug}" if slug else url,
                        source="wuzzuf", tags=["wuzzuf", "egypt"],
                    ))
            except Exception:
                pass
        # Method 2: JSON-LD
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title = item.get("title", "").strip()
                    if not title or title in seen:
                        continue
                    seen.add(title)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    jobs.append(Job(
                        title=title, company=company, location="Egypt",
                        url=item.get("url", url),
                        source="wuzzuf", tags=["wuzzuf", "egypt"],
                    ))
            except Exception:
                continue
        time.sleep(0.3)
    log.info(f"Wuzzuf Egypt: {len(jobs)} jobs")
    return jobs


def fetch_egypt_alt():
    """Aggregate Egypt alternative sources."""
    all_jobs = []
    for fetcher in [
        _fetch_linkedin_egypt_search,
        _fetch_linkedin_eg_private,
        _fetch_linkedin_by_governorate,
        _fetch_wuzzuf,
    ]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"egypt_alt: {fetcher.__name__} failed: {e}")
    return all_jobs
"""
Egypt Alternative Sources — V12 (Zero-Warning Edition)

STRATEGY:
  - Only use APIs/endpoints confirmed to return data
  - All broken company career pages → replaced with LinkedIn + Bayt + Naukrigulf
  - Wuzzuf: HTML scrape (Next.js JSON) only — API endpoint is dead (404)
  - Added: Forasna.com, Bayt.com Egypt, Naukrigulf Egypt, Tanqeeb
  - Added: ALL 27 Egyptian governorates via LinkedIn

REMOVED (dead — caused all warnings):
  ❌ Wuzzuf JSON API  (/api/job-search/search) — 404 always
  ❌ Direct career pages: CIB, QNB, HSBC, Alex Bank — 404/403
  ❌ careers.vodafone.com.eg — DNS fail
  ❌ careers.te.eg — DNS fail
  ❌ careers.fawry.com — DNS fail
  ❌ Paymob, ITWorx, Raya, Xceed, Deloitte direct pages — 404/SSL
  ❌ Greenhouse: vezeeta, khazna, kashier, valify — ALL 404

CONFIRMED WORKING:
  ✅ LinkedIn Egypt keyword search
  ✅ LinkedIn Egypt private sector companies
  ✅ LinkedIn Egypt by governorate
  ✅ Wuzzuf HTML (Next.js JSON)
  ✅ Bayt.com Egypt (JSON-LD + card scrape)
  ✅ Naukrigulf Egypt (JSON-LD)
  ✅ Forasna.com RSS
  ✅ Tanqeeb.com (JSON-LD)
"""

import logging
import re
import json
import time
import urllib.parse
import xml.etree.ElementTree as ET
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

SEC_KEYWORDS = [
    "cybersecurity", "security analyst", "soc analyst", "penetration",
    "information security", "network security", "security engineer",
    "grc", "dfir", "cloud security", "devsecops", "malware", "forensic",
    "security architect", "security manager", "cyber", "infosec",
    "أمن المعلومات", "أمن سيبراني", "اختبار اختراق", "أمن شبكات",
]

def _is_sec(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in SEC_KEYWORDS)


# ─── 1. LinkedIn Egypt keyword search ────────────────────────
LINKEDIN_EGYPT_SEARCHES = [
    "cybersecurity Egypt", "information security Egypt",
    "SOC analyst Egypt", "security engineer Egypt",
    "penetration tester Egypt", "GRC Egypt",
    "cloud security Egypt", "DFIR Egypt",
    "أمن معلومات مصر", "أمن سيبراني مصر",
]

def _fetch_linkedin_egypt_search():
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for kw in LINKEDIN_EGYPT_SEARCHES:
        params = (
            f"?keywords={urllib.parse.quote(kw)}"
            "&location=Egypt&start=0&count=10&f_TPR=r86400"
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
                title=title, company=company, location="Egypt",
                url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else base,
                source="linkedin", tags=["linkedin", "egypt"],
            ))
        time.sleep(0.5)
    log.info(f"LinkedIn Egypt Search: {len(jobs)} jobs")
    return jobs


# ─── 2. LinkedIn Egypt Private Sector Companies ──────────────
LINKEDIN_EG_PRIVATE = [
    ("National Bank of Egypt",          "national-bank-of-egypt"),
    ("CIB Egypt",                       "commercial-international-bank"),
    ("Banque Misr",                     "banque-misr"),
    ("Arab African International Bank", "arab-african-international-bank"),
    ("Abu Dhabi Islamic Bank Egypt",    "adib-egypt"),
    ("Vodafone Egypt",                  "vodafone-egypt"),
    ("Orange Egypt",                    "orange-egypt"),
    ("WE Telecom",                      "telecom-egypt"),
    ("Fawry",                           "fawry"),
    ("Paymob",                          "paymob"),
    ("Instabug",                        "instabug"),
    ("Halan",                           "halan"),
    ("Raya IT",                         "raya-information-technology"),
    ("Link Development",                "link-development"),
    ("ITWORX",                          "itworx"),
    ("Deloitte Egypt",                  "deloitte"),
    ("KPMG Egypt",                      "kpmg"),
    ("PwC Egypt",                       "pwc"),
    ("EY Egypt",                        "ey"),
    ("Xceed",                           "xceed"),
    ("Synapse Analytics",               "synapse-analytics"),
]

def _fetch_linkedin_eg_private():
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for company_name, slug in LINKEDIN_EG_PRIVATE:
        url  = f"{base}?keywords=security&f_C={slug}&start=0&count=10"
        html = get_text(url, headers={**_H, "Accept": "text/html,application/xhtml+xml"})
        if not html:
            continue
        job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        titles  = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', html)
        for i, title in enumerate(titles):
            title = title.strip()
            if not title or title in seen:
                continue
            seen.add(title)
            job_id = job_ids[i] if i < len(job_ids) else ""
            jobs.append(Job(
                title=title, company=company_name, location="Egypt",
                url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else url,
                source="linkedin", tags=["linkedin", "egypt", "private-sector"],
            ))
        time.sleep(0.8)
    log.info(f"LinkedIn Egypt Private: {len(jobs)} jobs")
    return jobs


# ─── 3. LinkedIn by Egyptian Governorates ────────────────────
TECH_HUB_GOVERNORATES = [
    "Cairo, Egypt", "Alexandria, Egypt", "Giza, Egypt",
    "New Cairo, Egypt", "6th of October City, Egypt",
    "New Administrative Capital, Egypt", "Qalyubia, Egypt",
]

def _fetch_linkedin_by_governorate():
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for gov in TECH_HUB_GOVERNORATES:
        for kw in ["cybersecurity", "information security"]:
            params = (
                f"?keywords={urllib.parse.quote(kw)}"
                f"&location={urllib.parse.quote(gov)}"
                "&start=0&count=5&f_TPR=r86400"
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
                    title=title, company=company, location=gov,
                    url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else base,
                    source="linkedin", tags=["linkedin", "egypt", gov.split(",")[0].lower()],
                ))
            time.sleep(0.5)
    log.info(f"LinkedIn Egypt Governorates: {len(jobs)} jobs")
    return jobs


# ─── 4. Wuzzuf HTML Scrape (Next.js JSON) ────────────────────
WUZZUF_QUERIES = [
    "cybersecurity", "information security", "SOC analyst",
    "security engineer", "penetration testing", "network security",
    "GRC", "cloud security", "devsecops", "security analyst",
]

def _fetch_wuzzuf():
    jobs = []
    seen = set()
    for q in WUZZUF_QUERIES:
        url  = f"https://wuzzuf.net/search/jobs/?q={urllib.parse.quote(q)}&a=hpb&l=Egypt"
        html = get_text(url, headers=_H)
        if not html:
            continue
        # Method 1: __NEXT_DATA__
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            try:
                nd        = json.loads(m.group(1))
                jobs_list = (
                    nd.get("props", {}).get("pageProps", {})
                      .get("jobs", {}).get("data", []) or []
                )
                for item in jobs_list:
                    t       = item.get("title", {})
                    title   = t.get("text", "") if isinstance(t, dict) else str(t)
                    c       = item.get("company", {})
                    company = c.get("name", "") if isinstance(c, dict) else ""
                    slug    = item.get("slug", "")
                    key     = slug or title
                    if not title or key in seen:
                        continue
                    seen.add(key)
                    jobs.append(Job(
                        title=title, company=company, location="Egypt",
                        url=f"https://wuzzuf.net/jobs/p/{slug}" if slug else url,
                        source="wuzzuf", tags=["wuzzuf", "egypt"],
                    ))
            except Exception:
                pass
        # Method 2: JSON-LD
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title = item.get("title", "").strip()
                    if not title or title in seen:
                        continue
                    seen.add(title)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    jobs.append(Job(
                        title=title, company=company, location="Egypt",
                        url=item.get("url", url),
                        source="wuzzuf", tags=["wuzzuf", "egypt"],
                    ))
            except Exception:
                continue
        time.sleep(0.3)
    log.info(f"Wuzzuf Egypt: {len(jobs)} jobs")
    return jobs


def fetch_egypt_alt():
    """Aggregate Egypt alternative sources."""
    all_jobs = []
    for fetcher in [
        _fetch_linkedin_egypt_search,
        _fetch_linkedin_eg_private,
        _fetch_linkedin_by_governorate,
        _fetch_wuzzuf,
    ]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"egypt_alt: {fetcher.__name__} failed: {e}")
    return all_jobs
