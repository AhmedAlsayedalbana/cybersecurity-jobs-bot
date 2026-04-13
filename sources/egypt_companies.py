"""
Egypt Cybersecurity Companies — V1
Expanded list of Egyptian companies in security sector + internship boards.

SOURCES:
  ✅ LinkedIn — Egyptian cybersecurity-specific companies
  ✅ Drjobpro.com — Arabic jobs portal
  ✅ Akhtaboot — Regional jobs
  ✅ Wuzzuf internships
  ✅ ITI / DEPI / NTI government training programs
  ✅ Forasna (fallback)
"""

import logging
import re
import time
import json
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

SEC_KW = [
    "cybersecurity", "security analyst", "soc analyst", "penetration",
    "information security", "network security", "security engineer",
    "grc", "dfir", "cloud security", "devsecops", "malware", "forensic",
    "security architect", "security manager", "cyber", "infosec",
    "أمن المعلومات", "أمن سيبراني", "اختبار اختراق",
]

def _is_sec(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in SEC_KW)


# ─── 1. Expanded LinkedIn Egypt Security Companies ──────────────
LINKEDIN_EG_SECURITY_COMPANIES = [
    # Pure Security Companies
    ("ITWorx",                           "itworx"),
    ("Raya IT",                          "raya-information-technology"),
    ("Xceed",                            "xceed"),
    ("Synapse Analytics",                "synapse-analytics"),
    ("Si-Ware Systems",                  "si-ware-systems"),
    ("Valeo Egypt",                      "valeo"),
    ("Instabug",                         "instabug"),
    ("Halan",                            "halan"),
    ("Link Development",                 "link-development"),
    ("ESET Egypt",                       "eset"),
    ("McAfee Egypt",                     "mcafee"),
    ("IBM Egypt",                        "ibm"),
    ("Cisco Egypt",                      "cisco"),
    ("Palo Alto Networks",               "palo-alto-networks"),
    ("Fortinet",                         "fortinet"),
    ("Check Point Egypt",                "check-point-software-technologies"),
    ("Trend Micro",                      "trend-micro"),
    ("Secureworks",                      "secureworks"),
    # Consulting
    ("Deloitte Egypt",                   "deloitte"),
    ("KPMG Egypt",                       "kpmg"),
    ("PwC Egypt",                        "pwc"),
    ("EY Egypt",                         "ey"),
    ("Accenture Egypt",                  "accenture"),
    ("BDO Egypt",                        "bdo-egypt"),
    # Banking / Fintech (heavy security hiring)
    ("National Bank of Egypt",           "national-bank-of-egypt"),
    ("CIB Egypt",                        "commercial-international-bank"),
    ("Banque Misr",                      "banque-misr"),
    ("Arab African International Bank",  "arab-african-international-bank"),
    ("Abu Dhabi Islamic Bank Egypt",     "adib-egypt"),
    ("Fawry",                            "fawry"),
    ("Paymob",                           "paymob"),
    ("Khazna",                           "khazna"),
    ("Valify",                           "valify-solutions"),
    ("Money Fellows",                    "money-fellows"),
    ("Kashier",                          "kashier"),
    # Telecom
    ("Vodafone Egypt",                   "vodafone-egypt"),
    ("Orange Egypt",                     "orange-egypt"),
    ("WE Telecom",                       "telecom-egypt"),
    ("Etisalat Egypt",                   "etisalat-egypt"),
    # Gov-adjacent tech
    ("MCIT Egypt",                       "ministry-of-communications-and-information-technology-egypt"),
    ("ITIDA",                            "itida"),
    ("Technology Innovation and Entrepreneurship Center", "tiec"),
    # MSS / SOC-as-a-service
    ("CyberTalents",                     "cybertalents"),
    ("C5 Alliance",                      "c5-alliance"),
    ("Help AG Egypt",                    "help-ag"),
    ("Solutionz Group",                  "solutionz-group"),
    ("Secured Globe",                    "secured-globe"),
    ("Digital Defense",                  "digital-defense"),
    ("Armada",                           "armada-cyber"),
]

def _fetch_linkedin_eg_security_companies():
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for company_name, slug in LINKEDIN_EG_SECURITY_COMPANIES:
        url = f"{base}?keywords=security&f_C={slug}&start=0&count=10"
        html = get_text(url, headers={**_H, "Accept": "text/html,application/xhtml+xml"})
        if not html:
            continue
        job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        titles  = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', html)
        for i, title in enumerate(titles):
            title = title.strip()
            if not title or title in seen or not _is_sec(title):
                continue
            seen.add(title)
            job_id = job_ids[i] if i < len(job_ids) else ""
            jobs.append(Job(
                title=title, company=company_name, location="Egypt",
                url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else url,
                source="linkedin", tags=["linkedin", "egypt", "security-company"],
            ))
        time.sleep(0.8)
    log.info(f"LinkedIn EG Security Companies: {len(jobs)} jobs")
    return jobs


# ─── 2. Drjobpro.com — Arabic/Egyptian jobs portal ───────────
def _fetch_drjobpro_egypt():
    jobs = []
    seen = set()
    queries = ["cybersecurity", "information security", "security analyst", "network security"]
    for q in queries:
        url = f"https://www.drjobpro.com/jobs-search/?q={urllib.parse.quote(q)}&country=egypt"
        html = get_text(url, headers=_H)
        if not html:
            continue
        # JSON-LD
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title = item.get("title", "").strip()
                    if not title or title in seen or not _is_sec(title):
                        continue
                    seen.add(title)
                    hiring = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    jobs.append(Job(
                        title=title, company=company or "Unknown",
                        location="Egypt",
                        url=item.get("url", url),
                        source="drjobpro", tags=["drjobpro", "egypt"],
                    ))
            except Exception:
                continue
        time.sleep(0.5)
    log.info(f"DrJobPro Egypt: {len(jobs)} jobs")
    return jobs


# ─── 3. Akhtaboot Egypt ───────────────────────────────────────
def _fetch_akhtaboot_egypt():
    jobs = []
    seen = set()
    queries = ["cybersecurity", "information security", "SOC analyst"]
    for q in queries:
        url = f"https://www.akhtaboot.com/en/jobs-in-egypt?q={urllib.parse.quote(q)}"
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title = item.get("title", "").strip()
                    if not title or title in seen or not _is_sec(title):
                        continue
                    seen.add(title)
                    hiring = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    jobs.append(Job(
                        title=title, company=company or "Unknown",
                        location="Egypt",
                        url=item.get("url", url),
                        source="akhtaboot", tags=["akhtaboot", "egypt"],
                    ))
            except Exception:
                continue
        time.sleep(0.5)
    log.info(f"Akhtaboot Egypt: {len(jobs)} jobs")
    return jobs


# ─── 4. Egypt Internships — ITI / DEPI / NTI / Wuzzuf ────────
INTERNSHIP_KEYWORDS = [
    "security intern", "cybersecurity intern", "soc intern",
    "information security trainee", "cyber trainee",
    "security graduate program", "security fresh grad",
    "أمن معلومات تدريب", "أمن سيبراني تدريب",
]

def _fetch_egypt_internships():
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

    # LinkedIn internship search Egypt
    for kw in INTERNSHIP_KEYWORDS[:5]:
        params = (
            f"?keywords={urllib.parse.quote(kw)}"
            "&location=Egypt&start=0&count=10&f_TPR=r2592000"  # last 30 days
            "&f_JT=I"  # Internship job type
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
                source="linkedin", tags=["linkedin", "egypt", "internship"],
            ))
        time.sleep(0.5)

    # Wuzzuf internships
    for q in ["security intern", "cybersecurity internship"]:
        url = f"https://wuzzuf.net/search/jobs/?q={urllib.parse.quote(q)}&a=hpb&l=Egypt&jt=Internship"
        html = get_text(url, headers=_H)
        if not html:
            continue
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            try:
                nd = json.loads(m.group(1))
                jobs_list = (
                    nd.get("props", {}).get("pageProps", {})
                      .get("jobs", {}).get("data", []) or []
                )
                for item in jobs_list:
                    t = item.get("title", {})
                    title = t.get("text", "") if isinstance(t, dict) else str(t)
                    c = item.get("company", {})
                    company = c.get("name", "") if isinstance(c, dict) else ""
                    slug = item.get("slug", "")
                    key = slug or title
                    if not title or key in seen:
                        continue
                    seen.add(key)
                    jobs.append(Job(
                        title=title, company=company, location="Egypt",
                        url=f"https://wuzzuf.net/jobs/p/{slug}" if slug else url,
                        source="wuzzuf", tags=["wuzzuf", "egypt", "internship"],
                    ))
            except Exception:
                pass
        time.sleep(0.3)

    log.info(f"Egypt Internships: {len(jobs)} jobs")
    return jobs


# ─── 5. Government Training Programs ─────────────────────────
def _fetch_gov_training_programs():
    """ITI, DEPI, NTI program listings"""
    jobs = []

    # ITI Egypt programs
    iti_url = "https://iti.gov.eg/iti/training-programs"
    html = get_text(iti_url, headers=_H)
    if html:
        programs = re.findall(
            r'<[^>]+>([^<]{10,100}(?:security|cyber|network|information technology)[^<]{0,60})</[^>]+>',
            html, re.IGNORECASE
        )
        for p in programs[:5]:
            title = re.sub(r'\s+', ' ', p).strip()
            if title:
                jobs.append(Job(
                    title=f"[Program] {title}",
                    company="ITI Egypt",
                    location="Egypt",
                    url=iti_url,
                    source="iti",
                    tags=["iti", "egypt", "training", "internship", "government"],
                ))

    # DEPI / NTI LinkedIn search
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for kw, company in [("DEPI cybersecurity", "DEPI Egypt"), ("NTI security", "NTI Egypt")]:
        params = f"?keywords={urllib.parse.quote(kw)}&location=Egypt&start=0&count=5"
        html = get_text(base + params, headers={**_H, "Accept": "text/html,application/xhtml+xml"})
        if not html:
            continue
        job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        titles  = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', html)
        for i, title in enumerate(titles):
            title = title.strip()
            if not title:
                continue
            job_id = job_ids[i] if i < len(job_ids) else ""
            jobs.append(Job(
                title=title, company=company, location="Egypt",
                url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else base,
                source="linkedin", tags=["linkedin", "egypt", "training", "internship"],
            ))
        time.sleep(0.5)

    log.info(f"Gov Training Programs: {len(jobs)} jobs")
    return jobs


def fetch_egypt_companies():
    """Fetch from expanded Egyptian company sources."""
    all_jobs = []
    for fetcher in [
        _fetch_linkedin_eg_security_companies,
        _fetch_drjobpro_egypt,
        _fetch_akhtaboot_egypt,
        _fetch_egypt_internships,
        _fetch_gov_training_programs,
    ]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"egypt_companies: {fetcher.__name__} failed: {e}")
    return all_jobs
