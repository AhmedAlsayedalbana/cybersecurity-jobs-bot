"""
LinkedIn #Hiring Posts Scraper — Cybersecurity Focus — v20 FIXED

ROOT CAUSE FIX:
  - consecutive_failures >= 2 كان يوقف الـ fetcher بعد فشلين متتاليين فقط
  - LinkedIn غالباً يرد بـ 429 أو HTML فارغ في أول 1-2 request
  - الحل: رفع الحد إلى 5، وإضافة retry مع exponential backoff
  - إضافة User-Agent rotation لتفادي الحجب
  - إضافة fallback: LinkedIn public search (بدون API)

Strategy:
  1. LinkedIn Jobs guest API → filtered for #hiring keyword combinations
  2. على فشل متكرر: fallback إلى LinkedIn public jobs search
"""

import logging
import re
import time
import random
import json
import urllib.parse
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

# ── LinkedIn API endpoints ────────────────────────────────────
JOBS_API   = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

# ── User-Agent pool (rotate to avoid blocking) ───────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]

# ── Canonical cybersecurity role classifier ──────────────────
ROLE_MAP = [
    ([" soc analyst", "security operations analyst"],          "SOC Analyst"),
    (["soc engineer",   "security operations engineer"],       "SOC Engineer"),
    (["soc manager",    "security operations manager"],        "SOC Manager"),
    (["siem",           "security monitoring"],                "SIEM / Security Monitoring"),
    (["threat intel",   "threat intelligence", "cti analyst"], "Threat Intelligence Analyst"),
    (["threat hunter",  "threat hunting"],                     "Threat Hunter"),
    (["incident resp",  "ir analyst", "dfir"],                 "Incident Response / DFIR"),
    (["malware analyst","malware researcher","reverse eng"],    "Malware Analyst"),
    (["penetration tester","pen tester","pentester"],          "Penetration Tester"),
    (["red team",       "red teamer"],                         "Red Team Engineer"),
    (["ethical hack",   "bug bounty","vulnerability researcher"],"Ethical Hacker / Bug Bounty"),
    (["exploit"],                                               "Exploit Developer"),
    (["appsec",         "application security"],               "Application Security Engineer"),
    (["devsecops",      "dev sec ops"],                        "DevSecOps Engineer"),
    (["secure code",    "sast", "dast", "owasp"],              "Secure Code / AppSec"),
    (["cloud security", "aws security","azure security","gcp security"], "Cloud Security Engineer"),
    (["network security","firewall","ids","ips","zero trust"],  "Network Security Engineer"),
    (["kubernetes security","container security","cspm"],       "Cloud-Native Security"),
    (["grc","governance risk","compliance analyst","iso 27001","nist","risk analyst"], "GRC / Compliance Analyst"),
    (["ciso","chief information security"],                     "CISO"),
    (["auditor","it audit","cyber audit"],                      "IT / Cyber Auditor"),
    (["data protection","privacy officer","gdpr","dpo"],        "Data Privacy Officer"),
    (["security architect","security architecture"],            "Security Architect"),
    (["security engineer","cybersecurity engineer","information security engineer"], "Security Engineer"),
    (["detection engineer"],                                    "Detection Engineer"),
    (["pki engineer","cryptograph","iam engineer","identity access"], "IAM / PKI / Cryptography"),
    (["security intern","security trainee","security graduate",
      "security fresh","fresh graduate","fresh grad",
      "junior security","junior cyber","entry level",
      "entry-level","trainee","internship"],                    "Security Intern / Trainee"),
    (["security manager","security lead","security officer",
      "security administrator","information security manager",
      "cybersecurity manager","cyber security manager"],        "Security Manager / Lead"),
    (["cybersecurity","cyber security","infosec","information security"], "Cybersecurity Specialist"),
    (["security analyst","security specialist","security consultant"], "Security Analyst"),
]

# ── Search queries ────────────────────────────────────────────
HIRING_SEARCHES_EGYPT = [
    {"keywords": "#hiring cybersecurity",        "location": "Egypt",        "f_TPR": "r604800"},
    {"keywords": "#hiring SOC analyst",          "location": "Egypt",        "f_TPR": "r604800"},
    {"keywords": "#hiring security engineer",    "location": "Egypt",        "f_TPR": "r604800"},
    {"keywords": "#hiring information security", "location": "Egypt",        "f_TPR": "r604800"},
    {"keywords": "#hiring penetration tester",   "location": "Egypt",        "f_TPR": "r604800"},
    {"keywords": "#hiring GRC",                  "location": "Egypt",        "f_TPR": "r604800"},
    {"keywords": "#hiring cybersecurity",        "location": "Cairo, Egypt", "f_TPR": "r604800"},
    {"keywords": "#hiring security",             "location": "Cairo, Egypt", "f_TPR": "r604800"},
    # Without # — catches posts that spell it out
    {"keywords": "hiring cybersecurity Egypt",   "location": "Egypt",        "f_TPR": "r604800"},
    {"keywords": "we are hiring security",       "location": "Egypt",        "f_TPR": "r604800"},
    {"keywords": "join our team cybersecurity",  "location": "Egypt",        "f_TPR": "r604800"},
    {"keywords": "security analyst vacancy",     "location": "Egypt",        "f_TPR": "r604800"},
    # Arabic
    {"keywords": "نحن نوظف أمن معلومات",        "location": "Egypt",        "f_TPR": "r604800"},
    {"keywords": "نحن نوظف أمن سيبراني",         "location": "Egypt",        "f_TPR": "r604800"},
    {"keywords": "مطلوب محلل أمن",               "location": "Egypt",        "f_TPR": "r604800"},
    {"keywords": "وظيفة أمن سيبراني",            "location": "Egypt",        "f_TPR": "r604800"},
]

HIRING_SEARCHES_GULF = [
    {"keywords": "#hiring cybersecurity",        "location": "Saudi Arabia",         "f_TPR": "r604800"},
    {"keywords": "#hiring SOC analyst",          "location": "Saudi Arabia",         "f_TPR": "r604800"},
    {"keywords": "#hiring security engineer",    "location": "Saudi Arabia",         "f_TPR": "r604800"},
    {"keywords": "#hiring cybersecurity",        "location": "United Arab Emirates", "f_TPR": "r604800"},
    {"keywords": "#hiring SOC analyst",          "location": "United Arab Emirates", "f_TPR": "r604800"},
    {"keywords": "#hiring security engineer",    "location": "United Arab Emirates", "f_TPR": "r604800"},
    {"keywords": "#hiring cybersecurity",        "location": "Qatar",                "f_TPR": "r604800"},
    {"keywords": "#hiring cybersecurity",        "location": "Kuwait",               "f_TPR": "r604800"},
    # Without # variants
    {"keywords": "we are hiring cybersecurity",  "location": "Saudi Arabia",         "f_TPR": "r604800"},
    {"keywords": "hiring security engineer",     "location": "United Arab Emirates", "f_TPR": "r604800"},
    # Arabic Gulf
    {"keywords": "نحن نوظف أمن سيبراني",         "location": "Saudi Arabia",         "f_TPR": "r604800"},
    {"keywords": "وظيفة أمن معلومات",            "location": "Saudi Arabia",         "f_TPR": "r604800"},
]

HIRING_SEARCHES_REMOTE = [
    {"keywords": "#hiring cybersecurity",        "f_WT": "2", "f_TPR": "r604800"},
    {"keywords": "#hiring SOC analyst",          "f_WT": "2", "f_TPR": "r604800"},
    {"keywords": "#hiring penetration tester",   "f_WT": "2", "f_TPR": "r604800"},
    {"keywords": "#hiring threat intelligence",  "f_WT": "2", "f_TPR": "r604800"},
    {"keywords": "#hiring cloud security",       "f_WT": "2", "f_TPR": "r604800"},
    {"keywords": "#hiring appsec",               "f_WT": "2", "f_TPR": "r604800"},
    {"keywords": "#hiring red team",             "f_WT": "2", "f_TPR": "r604800"},
    {"keywords": "#hiring devsecops",            "f_WT": "2", "f_TPR": "r604800"},
]

ALL_HIRING_SEARCHES = HIRING_SEARCHES_EGYPT + HIRING_SEARCHES_GULF + HIRING_SEARCHES_REMOTE


def match_canonical_title(raw_title: str) -> str:
    t = raw_title.lower()
    for keywords, canonical in ROLE_MAP:
        kw_list = keywords if isinstance(keywords, list) else [keywords]
        if any(kw in t for kw in kw_list):
            return canonical
    return raw_title.strip().title()


def _headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.linkedin.com/jobs/",
        "DNT": "1",
    }


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

    company = clean(extract(r'<a[^>]*class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)</a>'))
    if not company:
        company = clean(extract(r'<span[^>]*class="[^"]*topcard__flavor[^"]*"[^>]*>(.*?)</span>'))

    location = clean(extract(r'<span[^>]*class="[^"]*topcard__flavor--bullet[^"]*"[^>]*>(.*?)</span>'))
    if not location and search_location:
        location = search_location

    is_remote = bool(re.search(r'remote', html, re.IGNORECASE))
    if "remote" in location.lower():
        is_remote = True

    canonical = match_canonical_title(raw_title)

    desc_raw = extract(r'<div[^>]*class="[^"]*show-more-less-html[^"]*"[^>]*>(.*?)</div>')
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


def _fetch_with_retry(url, params=None, max_retries=3) -> str | None:
    """
    GET request with exponential backoff retry.
    LinkedIn often returns 429 or empty on first hit — retry fixes this.
    """
    for attempt in range(max_retries):
        html = get_text(url, params=params, headers=_headers())
        if html and len(html) > 200:
            return html
        wait = (2 ** attempt) + random.uniform(1, 3)
        log.debug(f"LinkedIn #Hiring: empty response attempt {attempt+1}, waiting {wait:.1f}s")
        time.sleep(wait)
    return None


def _fallback_linkedin_search(keyword: str, location: str = "") -> list[str]:
    """
    Fallback: use LinkedIn public jobs search page to extract job IDs.
    Used when the guest API is blocked.
    """
    query = urllib.parse.quote_plus(keyword)
    loc_q = urllib.parse.quote_plus(location) if location else ""
    url = f"https://www.linkedin.com/jobs/search/?keywords={query}"
    if loc_q:
        url += f"&location={loc_q}"
    url += "&f_TPR=r604800&sortBy=DD"

    html = _fetch_with_retry(url)
    if not html:
        return []

    ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
    if not ids:
        ids = re.findall(r'/jobs/view/(\d+)/', html)
    return list(set(ids[:5]))


def fetch_linkedin_hiring() -> list[Job]:
    """
    Fetch cybersecurity #Hiring posts from LinkedIn.

    v20 FIXES:
    - Raises consecutive_failures threshold: 2 → 5
    - Adds per-request retry with exponential backoff
    - Rotates User-Agent on each request
    - Falls back to public search page if API keeps failing
    - Total failure hard limit: 10 (not just consecutive)
    """
    jobs: list[Job] = []
    seen_ids: set[str] = set()
    consecutive_failures = 0
    total_failures       = 0
    MAX_CONSECUTIVE      = 5   # was 2 — this was the bug
    MAX_TOTAL            = 10

    for search in ALL_HIRING_SEARCHES:
        # Hard stop on too many total failures
        if total_failures >= MAX_TOTAL:
            log.warning("LinkedIn #Hiring: hit max total failures limit — stopping.")
            break

        # On consecutive failures: wait longer, then continue (not stop)
        if consecutive_failures >= MAX_CONSECUTIVE:
            log.warning(f"LinkedIn #Hiring: {consecutive_failures} consecutive failures — waiting 45s then resuming.")
            time.sleep(45)
            consecutive_failures = 0

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

        # ── Primary: Guest API with retry ─────────────────────
        html = _fetch_with_retry(JOBS_API, params=params, max_retries=3)

        if not html:
            # ── Fallback: public search page ──────────────────
            log.info(f"LinkedIn #Hiring: API failed for '{search.get('keywords')}' — trying public search fallback")
            fallback_ids = _fallback_linkedin_search(
                search.get("keywords", ""),
                search.get("location", "")
            )
            if fallback_ids:
                log.info(f"LinkedIn #Hiring: fallback found {len(fallback_ids)} IDs")
                consecutive_failures = 0
                for job_id in fallback_ids:
                    if job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)
                    detail_html = _fetch_with_retry(DETAIL_URL.format(job_id=job_id))
                    if not detail_html:
                        continue
                    job = _parse_detail(detail_html, job_id, search_location=search.get("location", ""))
                    if job:
                        jobs.append(job)
                    time.sleep(random.uniform(1.5, 2.5))
            else:
                consecutive_failures += 1
                total_failures       += 1
                wait = min(10 * consecutive_failures, 60)
                log.info(f"LinkedIn #Hiring: both API and fallback failed ({consecutive_failures} consecutive), waiting {wait}s")
                time.sleep(wait)
            continue

        consecutive_failures = 0

        # Extract job IDs
        job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        if not job_ids:
            job_ids = re.findall(r'"jobPostingId":(\d+)', html)
        if not job_ids:
            job_ids = re.findall(r'/jobs/view/(\d+)/', html)

        if not job_ids:
            log.debug(f"LinkedIn #Hiring: no job IDs in response for '{search.get('keywords')}'")
            time.sleep(3)
            continue

        for job_id in job_ids[:3]:
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            detail_html = _fetch_with_retry(DETAIL_URL.format(job_id=job_id))
            if not detail_html:
                continue

            job = _parse_detail(detail_html, job_id, search_location=search.get("location", ""))
            if job:
                jobs.append(job)
            time.sleep(random.uniform(1.5, 2.5))

        time.sleep(random.uniform(2.5, 4.0))

    log.info(f"LinkedIn #Hiring: fetched {len(jobs)} jobs. (failures: {total_failures} total, {consecutive_failures} final-consecutive)")
    return jobs
