"""
Egyptian Government & Major Employer Sources — V12 FAST

KEY FIX v27: Added TIME BUDGET to prevent hanging.
  - Companies: 60s max (was unlimited)
  - Governorates: 45s max, only 3 top cities × 2 keywords (was 9 × 5)

gov_egypt now focuses on GOVERNMENT companies only.
Private sector is handled by egypt_alt.py (avoids duplicate requests).
"""

import logging
import re
import time
import urllib.parse
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

JOBS_API = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

# Government & public sector + key private companies (double the original list)
LINKEDIN_EG_COMPANIES = [
    # Telecom
    ("Telecom Egypt (WE)",       "telecom-egypt"),
    ("Vodafone Egypt",           "vodafone-egypt"),
    ("Orange Egypt",             "orange-egypt"),
    ("Etisalat Egypt (e&)",      "etisalatmisr"),
    # Banks
    ("CIB Egypt",                "commercial-international-bank"),
    ("QNB Egypt",                "qnb-alahli"),
    ("HSBC Egypt",               "hsbc"),
    ("National Bank of Egypt",   "national-bank-of-egypt"),
    ("Banque Misr",              "banque-misr"),
    ("Central Bank of Egypt",    "central-bank-of-egypt"),
    ("Al Ahly Bank",             "ahly-bank"),
    ("Banque du Caire",          "banque-du-caire"),
    ("Arab African International Bank", "arab-african-international-bank"),
    ("Abu Dhabi Islamic Bank Egypt",    "adib-egypt"),
    ("Alex Bank",                "alexbank"),
    ("Egyptian Gulf Bank",       "egyptian-gulf-bank"),
    ("Housing and Development Bank", "housing-and-development-bank"),
    ("Attijariwafa Bank Egypt",  "attijariwafa-bank"),
    ("Emirates NBD Egypt",       "emirates-nbd"),
    ("Suez Canal Bank",          "suez-canal-bank"),
    ("First Abu Dhabi Bank Egypt", "fab"),
    ("Misr Insurance",           "misr-insurance"),
    # Fintech
    ("Fawry",                    "fawry"),
    ("Paymob",                   "paymob"),
    ("E-Finance",                "e-finance"),
    ("Khazna",                   "khazna"),
    ("Valify",                   "valify-solutions"),
    ("Money Fellows",            "money-fellows"),
    ("Geidea Egypt",             "geidea"),
    # IT & Consulting
    ("ITWorx",                   "itworx"),
    ("Raya Corporation",         "raya-corporation"),
    ("Xceed",                    "xceed"),
    ("Deloitte Egypt",           "deloitte"),
    ("KPMG Egypt",               "kpmg"),
    ("PwC Egypt",                "pwc"),
    ("EY Egypt",                 "ey"),
    ("Accenture Egypt",          "accenture"),
    ("IBM Egypt",                "ibm"),
    ("Cisco Egypt",              "cisco"),
    ("Microsoft Egypt",          "microsoft"),
    ("Oracle Egypt",             "oracle"),
    ("SAP Egypt",                "sap"),
    ("Huawei Egypt",             "huawei"),
    ("Ericsson Egypt",           "ericsson"),
    ("Nokia Egypt",              "nokia"),
    ("Dell Egypt",               "dell-technologies"),
    ("HP Egypt",                 "hp"),
    ("Capgemini Egypt",          "capgemini"),
    ("NTT Egypt",                "ntt-data"),
    ("Wipro Egypt",              "wipro"),
    ("Cognizant Egypt",          "cognizant"),
    ("Giza Systems",             "giza-systems"),
    ("Link Development",         "link-development"),
    ("Devoteam Egypt",           "devoteam"),
    ("Synapse Analytics",        "synapse-analytics"),
    ("Binaryville",              "binaryville"),
    ("BDO Egypt",                "bdo-egypt"),
    # Cybersecurity Specialists
    ("CyberTalents",             "cybertalents"),
    ("C5 Alliance",              "c5-alliance"),
    ("Help AG Egypt",            "help-ag"),
    ("Securemisr",               "securemisr"),
    ("Cybergate Egypt",          "cybergate"),
    ("Check Point Egypt",        "check-point-software-technologies"),
    ("Palo Alto Networks Egypt", "palo-alto-networks"),
    ("Fortinet Egypt",           "fortinet"),
    ("CrowdStrike",              "crowdstrike"),
    ("Darktrace",                "darktrace"),
    ("Kaspersky Egypt",          "kaspersky-lab"),
    ("Sophos Egypt",             "sophos"),
    ("Trend Micro Egypt",        "trend-micro"),
    ("ESET Egypt",               "eset"),
    ("CyberArk Egypt",           "cyberark"),
    ("Tenable Egypt",            "tenable"),
    ("SentinelOne Egypt",        "sentinelone"),
    ("Splunk Egypt",             "splunk"),
    ("Qualys Egypt",             "qualys"),
    ("Rapid7 Egypt",             "rapid7"),
    ("Varonis Egypt",            "varonis"),
    ("Secureworks Egypt",        "secureworks"),
    # Government / Public Sector
    ("MCIT Egypt",               "mcit-egypt"),
    ("ITIDA",                    "itida"),
    ("EG-CERT",                  "eg-cert"),
    ("ITI Egypt",                "information-technology-institute"),
    ("NTI Egypt",                "nti-egypt"),
    ("NTRA Egypt",               "ntra"),
    ("TIEC",                     "tiec"),
    ("MCDR Egypt",               "mcdr"),
    ("Egyptian Armed Forces IT",  "egyptian-armed-forces"),
    ("Cairo University",         "cairo-university"),
    ("Ain Shams University",     "ain-shams-university"),
    # Startups & E-commerce
    ("Instabug",                 "instabug"),
    ("Halan",                    "halan"),
    ("Swvl",                     "swvl"),
    ("Vezeeta",                  "vezeeta"),
    ("Bosta",                    "bosta"),
    ("Trella",                   "trella"),
    ("MaxAB",                    "maxab"),
    ("Dsquares",                 "dsquares"),
    ("Jumia Egypt",              "jumia"),
    ("Amazon Egypt",             "amazon"),
    ("Noon Egypt",               "noon"),
    ("Talabat Egypt",            "talabat"),
    ("Valeo Egypt",              "valeo"),
    ("Si Electronics",           "si-electronics"),
    ("Pioneers Holding",         "pioneers-holding"),
    # Utilities & Energy
    ("Egyptian Electricity",     "egyptian-electricity-holding-company"),
]


def _fetch_egypt_linkedin_companies():
    jobs = []
    seen = set()
    budget = 300  # v33: raised 150→300s — doubled company list
    t0 = time.time()

    for company_name, slug in LINKEDIN_EG_COMPANIES:
        if time.time() - t0 > budget:
            log.warning("gov_egypt/companies: budget hit — stopping early")
            break
        url = f"{JOBS_API}?keywords=security&f_C={slug}&start=0&count=10"
        html = get_text(url, headers=_H)
        if not html:
            continue
        job_ids  = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        titles   = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', html)
        for i, title in enumerate(titles):
            title = title.strip()
            if not title or title in seen:
                continue
            seen.add(title)
            job_id = job_ids[i] if i < len(job_ids) else ""
            jobs.append(Job(
                title=title, company=company_name,
                location="Egypt",
                url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else url,
                source="linkedin", tags=["linkedin", "egypt"],
            ))

    log.info(f"LinkedIn Egypt Companies: {len(jobs)} jobs")
    return jobs


# Expanded to 6 tech hubs × 4 keywords = 24 requests
TOP_TECH_HUBS = [
    "New Cairo, Egypt",
    "New Administrative Capital, Egypt",
    "Cairo, Egypt",
    "Alexandria, Egypt",
    "Giza, Egypt",
    "Smart Village, Egypt",
]

SECURITY_KEYWORDS = [
    "cybersecurity",
    "information security",
    "SOC analyst",
    "security engineer",
]


def _fetch_linkedin_by_governorate():
    jobs = []
    seen = set()
    budget = 150  # v33: raised 75→150s — expanded hubs+keywords
    t0 = time.time()

    for gov in TOP_TECH_HUBS:
        for kw in SECURITY_KEYWORDS:
            if time.time() - t0 > budget:
                log.warning("gov_egypt/governorates: budget hit — stopping early")
                break
            params = (
                f"?keywords={urllib.parse.quote(kw)}"
                f"&location={urllib.parse.quote(gov)}"
                "&start=0&count=5&f_TPR=r86400"
            )
            html = get_text(JOBS_API + params, headers=_H)
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
                    url=f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else JOBS_API,
                    source="linkedin", tags=["linkedin", "egypt", gov.split(",")[0].lower()],
                ))

    log.info(f"LinkedIn Egypt Governorates: {len(jobs)} jobs")
    return jobs


def fetch_gov_egypt():
    """Fetch from confirmed-live Egyptian sources. Both fetchers have time budgets."""
    all_jobs = []
    for fetcher in [_fetch_egypt_linkedin_companies, _fetch_linkedin_by_governorate]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"gov_egypt: {fetcher.__name__} failed: {e}")
    return all_jobs
