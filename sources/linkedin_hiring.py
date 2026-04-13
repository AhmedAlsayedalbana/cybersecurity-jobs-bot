"""
LinkedIn #Hiring Posts Scraper — Cybersecurity Focus

Strategy:
  LinkedIn members and companies regularly post with #Hiring + a job title.
  We scrape LinkedIn's public post/feed search for these, extract job info,
  match to a canonical cybersecurity job title, and surface them as leads.

  Two approaches used in parallel:
    1. LinkedIn Jobs guest API with f_AL=true (Easy Apply / recently posted)
       filtered for #hiring keyword combinations
    2. LinkedIn public search for posts with #hiring + security keywords
       parsed via regex/JSON-LD

Each hit is tagged as a "#Hiring post" so the Telegram message makes clear
this came from a human LinkedIn post, not an official job listing.
"""

import logging
import re
import time
import json
import urllib.parse
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

# ── LinkedIn API endpoints ────────────────────────────────────
JOBS_API   = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

# ── Canonical cybersecurity role classifier ──────────────────
# Maps keywords found in a post/title to a clean canonical title
ROLE_MAP = [
    # SOC / Blue Team
    (["soc analyst",    "security operations analyst"],          "SOC Analyst"),
    (["soc engineer",   "security operations engineer"],         "SOC Engineer"),
    (["soc manager",    "security operations manager"],          "SOC Manager"),
    (["siem",           "security monitoring"],                  "SIEM / Security Monitoring"),
    (["threat intel",   "threat intelligence", "cti analyst"],   "Threat Intelligence Analyst"),
    (["threat hunter",  "threat hunting"],                       "Threat Hunter"),
    (["incident resp",  "ir analyst", "dfir"],                   "Incident Response / DFIR"),
    (["malware analyst","malware researcher","reverse eng"],      "Malware Analyst"),
    # Pentest / Offensive
    (["penetration tester","pen tester","pentester"],            "Penetration Tester"),
    (["red team",       "red teamer"],                           "Red Team Engineer"),
    (["ethical hack",   "bug bounty","vulnerability researcher"],"Ethical Hacker / Bug Bounty"),
    (["exploit"],                                                 "Exploit Developer"),
    # AppSec / DevSecOps
    (["appsec",         "application security"],                 "Application Security Engineer"),
    (["devsecops",      "dev sec ops"],                          "DevSecOps Engineer"),
    (["secure code",    "sast", "dast", "owasp"],               "Secure Code / AppSec"),
    # Cloud / Infra
    (["cloud security", "aws security","azure security",
      "gcp security"],                                           "Cloud Security Engineer"),
    (["network security","firewall","ids","ips","zero trust"],   "Network Security Engineer"),
    (["kubernetes security","container security","cspm"],        "Cloud-Native Security"),
    # GRC
    (["grc",            "governance risk","compliance analyst",
      "iso 27001","nist","risk analyst"],                        "GRC / Compliance Analyst"),
    (["ciso",           "chief information security"],           "CISO"),
    (["auditor",        "it audit","cyber audit"],               "IT / Cyber Auditor"),
    (["data protection","privacy officer","gdpr","dpo"],         "Data Privacy Officer"),
    # Engineering / Architecture
    (["security architect","security architecture"],             "Security Architect"),
    (["security engineer","cybersecurity engineer",
      "information security engineer"],                          "Security Engineer"),
    (["detection engineer"],                                     "Detection Engineer"),
    (["pki engineer","cryptograph","iam engineer",
      "identity access"],                                        "IAM / PKI / Cryptography"),
    # Entry-level — MUST come before generic catch-alls
    (["security intern","security trainee","security graduate",
      "security fresh","fresh graduate","fresh grad",
      "junior security","junior cyber","entry level",
      "entry-level","trainee","internship"],                     "Security Intern / Trainee"),
    # Manager/Lead — MUST come before generic catch-alls (specific phrases)
    (["security manager","security lead","security officer",
      "security administrator","information security manager",
      "cybersecurity manager","cyber security manager"],         "Security Manager / Lead"),
    # General / Catch-all
    (["cybersecurity","cyber security","infosec",
      "information security"],                                   "Cybersecurity Specialist"),
    (["security analyst","security specialist",
      "security consultant"],                                    "Security Analyst"),
]

# ── Search queries for #Hiring posts ────────────────────────
# These combine the #hiring hashtag with cybersecurity role terms
# LinkedIn jobs API: keyword "#hiring cybersecurity" surfaces jobs where
# the description/title was posted with hiring intent
HIRING_SEARCHES_EGYPT = [
    {"keywords": "#hiring cybersecurity",          "location": "Egypt",         "f_TPR": "r604800"},
    {"keywords": "#hiring SOC analyst",            "location": "Egypt",         "f_TPR": "r604800"},
    {"keywords": "#hiring security engineer",      "location": "Egypt",         "f_TPR": "r604800"},
    {"keywords": "#hiring information security",   "location": "Egypt",         "f_TPR": "r604800"},
    {"keywords": "#hiring penetration tester",     "location": "Egypt",         "f_TPR": "r604800"},
    {"keywords": "#hiring GRC",                    "location": "Egypt",         "f_TPR": "r604800"},
    {"keywords": "#hiring cybersecurity",          "location": "Cairo, Egypt",  "f_TPR": "r604800"},
    {"keywords": "#hiring security",               "location": "Cairo, Egypt",  "f_TPR": "r604800"},
    {"keywords": "نحن نوظف أمن معلومات",           "location": "Egypt",         "f_TPR": "r604800"},
    {"keywords": "نحن نوظف أمن سيبراني",           "location": "Egypt",         "f_TPR": "r604800"},
]

HIRING_SEARCHES_GULF = [
    {"keywords": "#hiring cybersecurity",          "location": "Saudi Arabia",  "f_TPR": "r604800"},
    {"keywords": "#hiring SOC analyst",            "location": "Saudi Arabia",  "f_TPR": "r604800"},
    {"keywords": "#hiring security engineer",      "location": "Saudi Arabia",  "f_TPR": "r604800"},
    {"keywords": "#hiring cybersecurity",          "location": "United Arab Emirates", "f_TPR": "r604800"},
    {"keywords": "#hiring SOC analyst",            "location": "United Arab Emirates", "f_TPR": "r604800"},
    {"keywords": "#hiring security engineer",      "location": "United Arab Emirates", "f_TPR": "r604800"},
    {"keywords": "#hiring cybersecurity",          "location": "Qatar",         "f_TPR": "r604800"},
    {"keywords": "#hiring cybersecurity",          "location": "Kuwait",        "f_TPR": "r604800"},
]

HIRING_SEARCHES_REMOTE = [
    {"keywords": "#hiring cybersecurity",          "f_WT": "2",  "f_TPR": "r604800"},
    {"keywords": "#hiring SOC analyst",            "f_WT": "2",  "f_TPR": "r604800"},
    {"keywords": "#hiring penetration tester",     "f_WT": "2",  "f_TPR": "r604800"},
    {"keywords": "#hiring threat intelligence",    "f_WT": "2",  "f_TPR": "r604800"},
    {"keywords": "#hiring cloud security",         "f_WT": "2",  "f_TPR": "r604800"},
]

ALL_HIRING_SEARCHES = (
    HIRING_SEARCHES_EGYPT +
    HIRING_SEARCHES_GULF +
    HIRING_SEARCHES_REMOTE
)


# ── Canonical title matcher ──────────────────────────────────

def match_canonical_title(raw_title: str) -> str:
    """
    Map a raw job title string to a clean canonical cybersecurity role.
    Returns the canonical title, or the original if no match.
    """
    t = raw_title.lower()
    for keywords, canonical in ROLE_MAP:
        # Support both list and bare string in ROLE_MAP entries
        kw_list = keywords if isinstance(keywords, list) else [keywords]
        if any(kw in t for kw in kw_list):
            return canonical
    return raw_title.strip().title()


# ── Fetch ────────────────────────────────────────────────────

def _headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Referer": "https://www.linkedin.com/",
    }


def _parse_detail(html: str, job_id: str) -> Job | None:
    """Parse a LinkedIn job detail page into a Job, tagged as #Hiring."""
    def extract(pattern, default=""):
        m = re.search(pattern, html, re.DOTALL)
        return m.group(1).strip() if m else default

    def clean(text):
        return re.sub(r'<[^>]+>', '', text).strip()

    raw_title = clean(extract(
        r'<h2[^>]*class="[^"]*top-card-layout__title[^"]*"[^>]*>(.*?)</h2>'
    ))
    if not raw_title:
        raw_title = clean(extract(r'<title>(.*?)</title>'))
        raw_title = re.sub(r'\s*\|\s*LinkedIn.*', '', raw_title).strip()

    if not raw_title:
        return None

    company = clean(extract(
        r'<a[^>]*class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)</a>'
    ))
    if not company:
        company = clean(extract(
            r'<span[^>]*class="[^"]*topcard__flavor[^"]*"[^>]*>(.*?)</span>'
        ))

    location = clean(extract(
        r'<span[^>]*class="[^"]*topcard__flavor--bullet[^"]*"[^>]*>(.*?)</span>'
    ))
    is_remote = bool(re.search(r'remote', html, re.IGNORECASE))
    if "remote" in location.lower():
        is_remote = True

    # Canonical title matching
    canonical = match_canonical_title(raw_title)

    # Try to pull a short description snippet
    desc_raw = extract(
        r'<div[^>]*class="[^"]*show-more-less-html[^"]*"[^>]*>(.*?)</div>'
    )
    description = re.sub(r'<[^>]+>', ' ', desc_raw).strip()[:400] if desc_raw else ""

    return Job(
        title=canonical,
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
    Fetch cybersecurity #Hiring posts from LinkedIn.
    Returns Job objects tagged with source='linkedin_hiring'.
    """
    jobs: list[Job] = []
    seen_ids: set[str] = set()
    consecutive_failures = 0

    for search in ALL_HIRING_SEARCHES:
        if consecutive_failures >= 2:
            log.warning("LinkedIn #Hiring: too many consecutive failures — stopping early.")
            break

        params = {
            "keywords": search.get("keywords", ""),
            "start":    "0",
            "count":    "10",
        }
        if "location" in search:
            params["location"] = search["location"]
        if "f_WT" in search:
            params["f_WT"] = search["f_WT"]
        if "f_TPR" in search:
            params["f_TPR"] = search["f_TPR"]

        html = get_text(JOBS_API, params=params, headers=_headers())
        if not html:
            consecutive_failures += 1
            wait = 10 * consecutive_failures
            log.info(f"LinkedIn #Hiring: failure {consecutive_failures}, waiting {wait}s")
            time.sleep(wait)
            continue

        consecutive_failures = 0

        # Extract job IDs
        job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        if not job_ids:
            job_ids = re.findall(r'"jobPostingId":(\d+)', html)
        if not job_ids:
            job_ids = re.findall(r'/jobs/view/(\d+)/', html)

        for job_id in job_ids[:3]:
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            detail_html = get_text(
                DETAIL_URL.format(job_id=job_id),
                headers=_headers(),
            )
            if not detail_html:
                continue

            job = _parse_detail(detail_html, job_id)
            if job:
                jobs.append(job)
            time.sleep(1.5)

        time.sleep(3)

    log.info(f"LinkedIn #Hiring: fetched {len(jobs)} jobs.")
    return jobs
