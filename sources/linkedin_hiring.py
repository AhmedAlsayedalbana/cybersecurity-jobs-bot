"""
LinkedIn #Hiring Posts Scraper — v27

ROOT CAUSE (why 0 jobs every run):
  - The custom _fetch_with_retry() uses requests directly WITHOUT
    the bootstrapped LinkedIn session (CSRF token / JSESSIONID).
  - LinkedIn returns empty HTML for every unauthenticated guest request.
  - FIX: use http_utils.get_text() which auto-uses _linkedin_session.

STRATEGY v27:
  - Remove _fetch_with_retry (was bypassing CSRF auth)
  - Use http_utils.get_text() for ALL requests (correct session)
  - Focused, high-value searches only (Egypt + Gulf + Remote)
  - Budget: 8 minutes
"""

import logging
import re
import time
import random
import urllib.parse
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

JOBS_API   = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
BUDGET_SECS = 3 * 60  # v28: reduced from 8min — LinkedIn blocks anyway

ROLE_MAP = [
    (["soc analyst", "security operations analyst"],           "SOC Analyst"),
    (["soc engineer", "security operations engineer"],         "SOC Engineer"),
    (["soc manager", "security operations manager"],           "SOC Manager"),
    (["siem", "security monitoring"],                          "SIEM Engineer"),
    (["threat intel", "threat intelligence", "cti analyst"],   "Threat Intelligence Analyst"),
    (["threat hunter", "threat hunting"],                      "Threat Hunter"),
    (["incident resp", "ir analyst", "dfir"],                  "Incident Response / DFIR"),
    (["malware analyst", "malware researcher", "reverse eng"], "Malware Analyst"),
    (["penetration tester", "pen tester", "pentester"],        "Penetration Tester"),
    (["red team", "red teamer"],                               "Red Team Engineer"),
    (["ethical hack", "bug bounty", "vulnerability researcher"],"Ethical Hacker"),
    (["appsec", "application security"],                       "AppSec Engineer"),
    (["devsecops", "dev sec ops"],                             "DevSecOps Engineer"),
    (["cloud security", "aws security", "azure security"],     "Cloud Security Engineer"),
    (["network security", "firewall", "zero trust"],           "Network Security Engineer"),
    (["grc", "governance risk", "compliance analyst"],         "GRC / Compliance Analyst"),
    (["ciso", "chief information security"],                   "CISO"),
    (["security architect", "security architecture"],          "Security Architect"),
    (["security engineer", "cybersecurity engineer"],          "Security Engineer"),
    (["detection engineer"],                                   "Detection Engineer"),
    (["pki engineer", "cryptograph", "iam engineer"],          "IAM / PKI / Crypto"),
    (["intern", "trainee", "fresh grad", "junior security", "junior cyber"], "Security Intern / Junior"),
    (["security manager", "security lead", "security officer",
      "security administrator"],                               "Security Manager / Lead"),
    (["cybersecurity", "cyber security", "infosec", "information security"], "Cybersecurity Specialist"),
    (["security analyst", "security specialist", "security consultant"], "Security Analyst"),
]

# High-value searches only — Egypt, Gulf, Remote
ALL_HIRING_SEARCHES = [
    # Egypt — most important
    {"keywords": "cybersecurity",         "location": "Egypt",                        "f_TPR": "r604800"},
    {"keywords": "SOC analyst",           "location": "Egypt",                        "f_TPR": "r604800"},
    {"keywords": "security engineer",     "location": "Egypt",                        "f_TPR": "r604800"},
    {"keywords": "information security",  "location": "Egypt",                        "f_TPR": "r604800"},
    {"keywords": "penetration tester",    "location": "Egypt",                        "f_TPR": "r604800"},
    {"keywords": "GRC",                   "location": "Egypt",                        "f_TPR": "r604800"},
    {"keywords": "cybersecurity",         "location": "Cairo, Egypt",                 "f_TPR": "r604800"},
    {"keywords": "security analyst",      "location": "New Cairo, Egypt",             "f_TPR": "r604800"},
    {"keywords": "cybersecurity",         "location": "New Administrative Capital, Egypt", "f_TPR": "r604800"},
    {"keywords": "security",             "location": "6th of October City, Egypt",   "f_TPR": "r604800"},
    # Gulf
    {"keywords": "cybersecurity",        "location": "Saudi Arabia",                  "f_TPR": "r604800"},
    {"keywords": "SOC analyst",          "location": "Saudi Arabia",                  "f_TPR": "r604800"},
    {"keywords": "security engineer",    "location": "Saudi Arabia",                  "f_TPR": "r604800"},
    {"keywords": "cybersecurity",        "location": "United Arab Emirates",          "f_TPR": "r604800"},
    {"keywords": "SOC analyst",          "location": "United Arab Emirates",          "f_TPR": "r604800"},
    {"keywords": "cybersecurity",        "location": "Qatar",                         "f_TPR": "r604800"},
    # Remote
    {"keywords": "cybersecurity",        "f_WT": "2",                                 "f_TPR": "r604800"},
    {"keywords": "SOC analyst",          "f_WT": "2",                                 "f_TPR": "r604800"},
    {"keywords": "penetration tester",   "f_WT": "2",                                 "f_TPR": "r604800"},
    {"keywords": "threat intelligence",  "f_WT": "2",                                 "f_TPR": "r604800"},
    {"keywords": "cloud security",       "f_WT": "2",                                 "f_TPR": "r604800"},
]


def match_canonical_title(raw_title: str) -> str:
    t = raw_title.lower()
    for keywords, canonical in ROLE_MAP:
        if any(kw in t for kw in keywords):
            return canonical
    return raw_title.strip().title()


def _parse_detail(html: str, job_id: str, search_location: str = "") -> Job | None:
    def extract(pattern, default=""):
        m = re.search(pattern, html, re.DOTALL)
        return m.group(1).strip() if m else default

    def clean(text):
        return re.sub(r'<[^>]+>', '', text).strip()

    raw_title = clean(extract(r'<h2[^>]*class="[^"]*top-card-layout__title[^"]*"[^>]*>(.*?)</h2>'))
    if not raw_title:
        raw_title = clean(extract(r'<title>(.*?)</title>'))
        raw_title = re.sub(r'\s*\|\s*LinkedIn.*', '', raw_title).strip()
    if not raw_title:
        return None

    company  = clean(extract(r'<a[^>]*class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)</a>'))
    if not company:
        company = clean(extract(r'<span[^>]*class="[^"]*topcard__flavor[^"]*"[^>]*>(.*?)</span>'))

    location = clean(extract(r'<span[^>]*class="[^"]*topcard__flavor--bullet[^"]*"[^>]*>(.*?)</span>'))
    if not location and search_location:
        location = search_location

    is_remote = bool(re.search(r'remote', html, re.IGNORECASE))

    desc_raw    = extract(r'<div[^>]*class="[^"]*show-more-less-html[^"]*"[^>]*>(.*?)</div>')
    description = re.sub(r'<[^>]+>', ' ', desc_raw).strip()[:400] if desc_raw else ""

    return Job(
        title=match_canonical_title(raw_title),
        company=company or "Unknown",
        location=location or "Not specified",
        url=f"https://www.linkedin.com/jobs/view/{job_id}/",
        source="linkedin_hiring",
        original_source=f"#Hiring — {raw_title}",
        description=description,
        tags=["#hiring", "linkedin", "hiring-post"],
        is_remote=is_remote,
    )


def fetch_linkedin_hiring() -> list[Job]:
    """
    Fetch cybersecurity hiring posts from LinkedIn.

    v27 KEY FIX:
      Uses http_utils.get_text() for ALL requests.
      http_utils automatically uses _linkedin_session (with valid CSRF token).
      The old _fetch_with_retry() was bypassing this → 0 jobs every run.
    """
    jobs: list[Job] = []
    seen_ids: set[str] = set()
    consecutive_failures = 0
    total_failures = 0
    MAX_CONSECUTIVE = 4
    MAX_TOTAL = 12
    start_time = time.time()

    for search in ALL_HIRING_SEARCHES:
        if time.time() - start_time > BUDGET_SECS:
            log.warning(f"LinkedIn #Hiring: budget exhausted after {len(jobs)} jobs.")
            break
        if total_failures >= MAX_TOTAL:
            log.warning("LinkedIn #Hiring: max failures reached — stopping.")
            break
        if consecutive_failures >= MAX_CONSECUTIVE:
            log.warning(f"LinkedIn #Hiring: {consecutive_failures} consecutive failures — waiting 15s.")
            time.sleep(15)   # was 30s
            consecutive_failures = 0

        params = {
            "keywords": search.get("keywords", ""),
            "start": "0",
            "count": "10",
        }
        if "location" in search:
            params["location"] = search["location"]
        if "f_WT" in search:
            params["f_WT"] = search["f_WT"]
        if "f_TPR" in search:
            params["f_TPR"] = search["f_TPR"]

        # KEY FIX: use http_utils.get_text → uses _linkedin_session with CSRF token
        html = get_text(JOBS_API, params=params)

        if not html or len(html) < 200:
            consecutive_failures += 1
            total_failures += 1
            wait = min(5 * consecutive_failures, 20)   # was min(8*n, 40)
            log.debug(f"LinkedIn #Hiring: empty for '{search.get('keywords')}' — waiting {wait}s")
            time.sleep(wait)
            continue

        consecutive_failures = 0

        job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        if not job_ids:
            job_ids = re.findall(r'"jobPostingId":(\d+)', html)
        if not job_ids:
            job_ids = re.findall(r'/jobs/view/(\d+)/', html)

        for job_id in job_ids[:5]:
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            detail_html = get_text(DETAIL_URL.format(job_id=job_id))
            if not detail_html:
                continue

            job = _parse_detail(detail_html, job_id, search_location=search.get("location", ""))
            if job:
                jobs.append(job)
            time.sleep(random.uniform(1.0, 2.0))

        time.sleep(random.uniform(2.0, 3.5))

    log.info(f"LinkedIn #Hiring: fetched {len(jobs)} jobs. (failures: {total_failures})")
    return jobs
