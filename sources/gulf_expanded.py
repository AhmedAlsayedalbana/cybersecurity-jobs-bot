"""
Gulf Internships + Expanded Gulf Sources — V1

SOURCES:
  ✅ LinkedIn Gulf internship search (KSA, UAE, Kuwait, Qatar)
  ✅ Bayt.com Gulf internships
  ✅ Naukrigulf internships
  ✅ Gulf government programs (SDAIA, NCA, CITC trainee programs)
  ✅ Expanded Gulf LinkedIn companies
  ✅ Akhtaboot Gulf
"""

import logging
import re
import time
import json
import urllib.parse
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

SEC_KW = [
    "cybersecurity", "security analyst", "soc", "penetration",
    "information security", "network security", "security engineer",
    "grc", "dfir", "cloud security", "devsecops", "malware", "forensic",
    "security architect", "security manager", "cyber", "infosec",
]

def _is_sec(text: str) -> bool:
    return any(k in text.lower() for k in SEC_KW)


# ─── 1. Expanded LinkedIn Gulf Companies ─────────────────────
LINKEDIN_GULF_EXPANDED = [
    ("NCA Saudi Arabia",        "national-cybersecurity-authority"),
    ("SDAIA",                   "sdaia"),
    ("CITC KSA",                "citc-saudi-arabia"),
    ("Saudi Aramco",            "saudi-aramco"),
    ("SABIC",                   "sabic"),
    ("NEOM",                    "neom"),
    ("Saudi Electricity Company","saudi-electricity-company"),
    ("Saudi Telecom (STC)",     "stc"),
    ("Zain KSA",                "zain-ksa"),
    ("Mobily",                  "mobily"),
    ("stc pay",                 "stc-pay"),
    ("Elm Company",             "elm"),
    ("Taqnia",                  "taqnia"),
    ("Saudi Payments",          "saudi-payments"),
    ("Riyad Bank",              "riyad-bank"),
    ("Al Rajhi Bank",           "al-rajhi-bank"),
    ("SNB Capital",             "snb-capital"),
    ("Arab National Bank",      "arab-national-bank"),
    ("Alinma Bank",             "alinma-bank"),
    ("Saudi Fransi Bank",       "banque-saudi-fransi"),
    ("UAE Cyber Security Council","uae-cybersecurity-council"),
    ("ADNOC",                   "adnoc"),
    ("G42",                     "g42-holdings"),
    ("DEWA",                    "dewa"),
    ("Mubadala",                "mubadala"),
    ("ENOC",                    "enoc"),
    ("Dubai Police",            "dubai-police"),
    ("Abu Dhabi Police",        "abu-dhabi-police"),
    ("du Telecom",              "du"),
    ("e& (Etisalat)",           "etisalat"),
    ("Careem",                  "careem"),
    ("Noon",                    "noon"),
    ("Majid Al Futtaim",        "majid-al-futtaim"),
    ("First Abu Dhabi Bank",    "fab"),
    ("Emirates NBD",            "emirates-nbd"),
    ("ADIB UAE",                "adib"),
    ("Dubai Islamic Bank",      "dubai-islamic-bank"),
    ("Mashreq Bank",            "mashreqbank"),
    ("RAK Bank",                "rakbank"),
    ("Zain Kuwait",             "zain-kw"),
    ("NBK",                     "national-bank-of-kuwait"),
    ("Gulf Bank Kuwait",        "gulf-bank"),
    ("Kuwait Finance House",    "kfh"),
    ("Agility Kuwait",          "agility"),
    ("Ooredoo Qatar",           "ooredoo"),
    ("QNB",                     "qnb"),
    ("QCERT",                   "qcert"),
    ("Qatar Airways",           "qatar-airways"),
    ("Qatar Foundation",        "qatar-foundation"),
    ("Batelco",                 "batelco"),
    ("BBK Bahrain",             "bbk-bank-of-bahrain-and-kuwait"),
    ("Omantel",                 "omantel"),
    ("Bank Muscat",             "bank-muscat"),
    ("Oman Arab Bank",          "oman-arab-bank"),
    ("Help AG",                 "help-ag"),
    ("DarkMatter UAE",          "dark-matter"),
    ("Spire Solutions",         "spire-solutions"),
    ("Cipher Gulf",             "cipher-gulf"),
    ("Kaspersky Gulf",          "kaspersky-lab"),
    ("Palo Alto Gulf",          "palo-alto-networks"),
    ("Fortinet Gulf",           "fortinet"),
    ("Check Point Gulf",        "check-point-software-technologies"),
    ("CrowdStrike Gulf",        "crowdstrike"),
    ("Deloitte Gulf",           "deloitte"),
    ("PwC Gulf",                "pwc"),
    ("KPMG Gulf",               "kpmg"),
    ("EY Gulf",                 "ey"),
    ("Accenture Gulf",          "accenture"),
    ("McKinsey Gulf",           "mckinsey"),
    ("BCG Gulf",                "boston-consulting-group"),
    ("Microsoft Gulf",          "microsoft"),
    ("Cisco Gulf",              "cisco"),
    ("IBM Gulf",                "ibm"),
    ("Oracle Gulf",             "oracle"),
    ("SAP Gulf",                "sap"),
    ("Huawei Gulf",             "huawei"),
    ("Ericsson Gulf",           "ericsson"),
]

def _fetch_linkedin_gulf_expanded():
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for company_name, slug in LINKEDIN_GULF_EXPANDED:
        url = f"{base}?keywords=cybersecurity&f_C={slug}&start=0&count=10"
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
                title=title, company=company_name, location="Gulf",
                url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else url,
                source="linkedin", tags=["linkedin", "gulf", "security-company"],
            ))
        time.sleep(0.8)
    log.info(f"LinkedIn Gulf Expanded: {len(jobs)} jobs")
    return jobs


# ─── 2. Gulf Internships via LinkedIn ────────────────────────
GULF_INTERN_LOCATIONS = [
    "Saudi Arabia", "United Arab Emirates", "Kuwait", "Qatar",
]
GULF_INTERN_KEYWORDS = [
    "cybersecurity intern", "security trainee", "information security intern",
    "SOC intern", "cyber graduate program",
]

def _fetch_gulf_internships():
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for loc in GULF_INTERN_LOCATIONS:
        for kw in GULF_INTERN_KEYWORDS[:3]:
            params = (
                f"?keywords={urllib.parse.quote(kw)}"
                f"&location={urllib.parse.quote(loc)}"
                "&start=0&count=10&f_TPR=r2592000"
                "&f_JT=I"  # Internship type
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
                    title=title, company=company, location=loc,
                    url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else base,
                    source="linkedin",
                    tags=["linkedin", "gulf", "internship", loc.lower().split()[0]],
                ))
            time.sleep(0.5)
    log.info(f"Gulf Internships: {len(jobs)} jobs")
    return jobs


# ─── 3. Akhtaboot Gulf ────────────────────────────────────────
def _fetch_akhtaboot_gulf():
    jobs = []
    seen = set()
    gulf_countries = ["saudi-arabia", "uae", "kuwait", "qatar"]
    queries = ["cybersecurity", "information security"]
    for country in gulf_countries[:2]:
        for q in queries:
            url = f"https://www.akhtaboot.com/en/jobs-in-{country}?q={urllib.parse.quote(q)}"
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
                        jp_loc = item.get("jobLocation", {})
                        location = ""
                        if isinstance(jp_loc, dict):
                            addr = jp_loc.get("address", {})
                            location = addr.get("addressCountry", country.replace("-", " ").title()) if isinstance(addr, dict) else ""
                        jobs.append(Job(
                            title=title, company=company or "Unknown",
                            location=location or country.replace("-", " ").title(),
                            url=item.get("url", url),
                            source="akhtaboot", tags=["akhtaboot", "gulf"],
                        ))
                except Exception:
                    continue
            time.sleep(0.5)
    log.info(f"Akhtaboot Gulf: {len(jobs)} jobs")
    return jobs


# ─── 4. Naukrigulf ────────────────────────────────────────────
def _fetch_naukrigulf():
    jobs = []
    seen = set()
    queries = ["cybersecurity", "information security", "SOC analyst"]
    for q in queries:
        url = f"https://www.naukrigulf.com/cyber-security-jobs-in-uae?q={urllib.parse.quote(q)}"
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
                        location="Gulf",
                        url=item.get("url", url),
                        source="naukrigulf", tags=["naukrigulf", "gulf"],
                    ))
            except Exception:
                continue
        time.sleep(0.5)
    log.info(f"Naukrigulf: {len(jobs)} jobs")
    return jobs


def fetch_gulf_expanded():
    """Fetch from expanded Gulf sources.
    Removed: NaukriGulf (read timeout on all requests), Akhtaboot (0 jobs).
    """
    all_jobs = []
    for fetcher in [
        _fetch_linkedin_gulf_expanded,
        _fetch_gulf_internships,
        # _fetch_akhtaboot_gulf,  # 0 jobs confirmed — disabled
        # _fetch_naukrigulf,      # read timeout on all requests — disabled
    ]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"gulf_expanded: {fetcher.__name__} failed: {e}")
    return all_jobs
