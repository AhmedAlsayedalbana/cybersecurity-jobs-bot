"""
LinkedIn Guest API — Cybersecurity-focused searches.
No login or API key required.

Focuses on:
  1. Egypt (onsite + recent)
  2. Gulf (Saudi/UAE)
  3. Remote worldwide

Note: LinkedIn may rate-limit or block scrapers. Failures are non-fatal.
"""

import logging
import re
import time
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

SEARCH_URL  = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL  = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

# ── Egypt — All Governorates (HIGHEST PRIORITY) ──
EGYPT_SEARCHES = [
    # Cairo — core roles only (city-level granularity handled by egypt_alt.py)
    {"keywords": "cybersecurity",        "location": "Cairo, Egypt",   "f_TPR": "r86400"},
    {"keywords": "SOC analyst",          "location": "Cairo, Egypt",   "f_TPR": "r86400"},
    {"keywords": "penetration tester",   "location": "Cairo, Egypt",   "f_TPR": "r86400"},
    {"keywords": "security engineer",    "location": "Cairo, Egypt",   "f_TPR": "r86400"},
    {"keywords": "security intern",      "location": "Cairo, Egypt",   "f_TPR": "r86400"},
    # Broad Egypt — roles not covered by city searches
    {"keywords": "cybersecurity",        "location": "Egypt",          "f_TPR": "r86400"},
    {"keywords": "GRC analyst",          "location": "Egypt",          "f_TPR": "r86400"},
    {"keywords": "DFIR",                 "location": "Egypt",          "f_TPR": "r86400"},
    {"keywords": "threat intelligence",  "location": "Egypt",          "f_TPR": "r86400"},
    {"keywords": "cloud security",       "location": "Egypt",          "f_TPR": "r86400"},
    {"keywords": "security trainee",     "location": "Egypt",          "f_TPR": "r86400"},
]

# ── Gulf — Core Coverage (SECOND PRIORITY) ──
GULF_SEARCHES = [
    # Saudi Arabia
    {"keywords": "cybersecurity",        "location": "Riyadh, Saudi Arabia",            "f_TPR": "r86400"},
    {"keywords": "SOC analyst",          "location": "Saudi Arabia",                    "f_TPR": "r86400"},
    {"keywords": "penetration tester",   "location": "Saudi Arabia",                    "f_TPR": "r86400"},
    {"keywords": "GRC analyst",          "location": "Saudi Arabia",                    "f_TPR": "r86400"},
    {"keywords": "junior security",      "location": "Saudi Arabia",                    "f_TPR": "r86400"},
    {"keywords": "information security", "location": "Saudi Arabia",                    "f_TPR": "r86400"},
    # UAE
    {"keywords": "cybersecurity",        "location": "Dubai, United Arab Emirates",     "f_TPR": "r86400"},
    {"keywords": "SOC analyst",          "location": "United Arab Emirates",            "f_TPR": "r86400"},
    {"keywords": "security engineer",    "location": "United Arab Emirates",            "f_TPR": "r86400"},
    {"keywords": "junior security",      "location": "United Arab Emirates",            "f_TPR": "r86400"},
    # Qatar, Kuwait, Bahrain, Oman
    {"keywords": "cybersecurity",        "location": "Doha, Qatar",                     "f_TPR": "r86400"},
    {"keywords": "cybersecurity",        "location": "Kuwait City, Kuwait",             "f_TPR": "r86400"},
    {"keywords": "cybersecurity",        "location": "Manama, Bahrain",                 "f_TPR": "r86400"},
    {"keywords": "cybersecurity",        "location": "Muscat, Oman",                   "f_TPR": "r86400"},
]

# ── Remote worldwide (LOWEST PRIORITY) ──
REMOTE_SEARCHES = [
    {"keywords": "cybersecurity engineer",        "f_WT": "2", "f_TPR": "r86400"},
    {"keywords": "SOC analyst",                   "f_WT": "2", "f_TPR": "r86400"},
    {"keywords": "penetration tester",            "f_WT": "2", "f_TPR": "r86400"},
    {"keywords": "threat intelligence analyst",   "f_WT": "2", "f_TPR": "r86400"},
    {"keywords": "application security engineer", "f_WT": "2", "f_TPR": "r86400"},
    {"keywords": "cloud security engineer",       "f_WT": "2", "f_TPR": "r86400"},
    {"keywords": "devsecops",                     "f_WT": "2", "f_TPR": "r86400"},
    {"keywords": "red team",                      "f_WT": "2", "f_TPR": "r86400"},
]

# ── Extra Egypt searches — unique value only ────────
EGYPT_EXTRA_SEARCHES = [
    # Arabic keywords — catches local HR posts
    {"keywords": "أمن معلومات",               "location": "Egypt",        "f_TPR": "r604800"},
    {"keywords": "أمن سيبراني",               "location": "Egypt",        "f_TPR": "r604800"},
    {"keywords": "اختبار اختراق",             "location": "Egypt",        "f_TPR": "r604800"},
    # Specific roles not in core list
    {"keywords": "vulnerability assessment",   "location": "Egypt",        "f_TPR": "r604800"},
    {"keywords": "compliance analyst",         "location": "Egypt",        "f_TPR": "r604800"},
    {"keywords": "appsec",                     "location": "Egypt",        "f_TPR": "r604800"},
    # Internship / fresh grad
    {"keywords": "cybersecurity internship",   "location": "Egypt",        "f_TPR": "r2592000"},
    {"keywords": "IT security fresh graduate", "location": "Egypt",        "f_TPR": "r2592000"},
    # Key employer hubs
    {"keywords": "cybersecurity",              "location": "Smart Village, Egypt", "f_TPR": "r604800"},
    {"keywords": "cybersecurity",              "location": "New Administrative Capital, Egypt", "f_TPR": "r604800"},
]

# ── Extra Gulf searches — unique value only ─────────
GULF_EXTRA_SEARCHES = [
    # Arabic keywords Gulf
    {"keywords": "أمن سيبراني",               "location": "Saudi Arabia",         "f_TPR": "r604800"},
    {"keywords": "أمن معلومات",               "location": "Saudi Arabia",         "f_TPR": "r604800"},
    {"keywords": "أمن سيبراني",               "location": "United Arab Emirates", "f_TPR": "r604800"},
    # Specific roles
    {"keywords": "vulnerability management",   "location": "Saudi Arabia",         "f_TPR": "r604800"},
    {"keywords": "appsec",                     "location": "United Arab Emirates", "f_TPR": "r604800"},
    {"keywords": "red team",                   "location": "Saudi Arabia",         "f_TPR": "r604800"},
    {"keywords": "devsecops",                  "location": "United Arab Emirates", "f_TPR": "r604800"},
    # Internship Gulf
    {"keywords": "cybersecurity internship",   "location": "Saudi Arabia",         "f_TPR": "r2592000"},
    {"keywords": "security trainee",           "location": "United Arab Emirates", "f_TPR": "r2592000"},
]

# Combined in priority order: Egypt → Egypt Extra → Gulf → Gulf Extra → Remote
SEARCHES = (
    EGYPT_SEARCHES
    + EGYPT_EXTRA_SEARCHES
    + GULF_SEARCHES
    + GULF_EXTRA_SEARCHES
    + REMOTE_SEARCHES
)




def _fetch_with_retry(url, params=None, max_retries=3) -> str | None:
    """GET with exponential backoff — LinkedIn often returns empty on first hit.
    NOTE: Do NOT pass headers= here — the bootstrapped session in http_utils
    already carries the correct Csrf-Token. Overriding headers kills the token.
    """
    import random
    for attempt in range(max_retries):
        html = get_text(url, params=params)  # no headers= override
        if html and len(html) > 200:
            return html
        wait = (2 ** attempt) + random.uniform(1, 3)
        log.debug(f"LinkedIn: empty response attempt {attempt+1}, waiting {wait:.1f}s")
        time.sleep(wait)
    return None


def fetch_linkedin() -> list[Job]:
    """
    Fetch cybersecurity jobs from LinkedIn guest API.
    V23: trimmed search list (107→52 queries), added 8-minute wall-clock
    budget to prevent GitHub Actions timeout.
    """
    import random
    BUDGET_SECONDS = 12 * 60  # v33: raised 8→12 minutes for LinkedIn
    _start = time.time()

    jobs = []
    seen_ids: set[str] = set()
    consecutive_failures = 0
    total_failures = 0
    MAX_CONSECUTIVE = 4   # stop sooner, don't waste budget on lost cause
    MAX_TOTAL       = 8   # was 12

    for search in SEARCHES:
        if time.time() - _start > BUDGET_SECONDS:
            log.warning(f"LinkedIn: 12-minute budget exhausted after {len(jobs)} jobs — stopping early.")
            break

        if total_failures >= MAX_TOTAL:
            log.warning("LinkedIn: hit max total failures — stopping.")
            break

        if consecutive_failures >= MAX_CONSECUTIVE:
            log.warning(f"LinkedIn: {consecutive_failures} consecutive failures — waiting 20s.")
            time.sleep(20)   # was 45s — don't waste budget
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

        html = _fetch_with_retry(SEARCH_URL, params=params, max_retries=3)
        if not html:
            consecutive_failures += 1
            total_failures += 1
            wait = min(5 * consecutive_failures, 20)   # was min(10*n, 60)
            log.info(f"LinkedIn: failure {consecutive_failures}, waiting {wait}s")
            time.sleep(wait)
            continue

        consecutive_failures = 0

        # Extract job IDs
        job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        if not job_ids:
            job_ids = re.findall(r'"jobPostingId":(\d+)', html)
        if not job_ids:
            job_ids = re.findall(r'/jobs/view/(\d+)/', html)

        for job_id in job_ids[:5]:  # increased from 3 → 5
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            detail_html = _fetch_with_retry(DETAIL_URL.format(job_id=job_id), max_retries=2)
            if not detail_html:
                continue

            job = _parse_detail(detail_html, job_id)
            if job:
                jobs.append(job)
            time.sleep(random.uniform(1.5, 2.5))

        time.sleep(random.uniform(2.5, 4.0))

    log.info(f"LinkedIn: fetched {len(jobs)} jobs. (failures: {total_failures})")
    return jobs


def _parse_detail(html: str, job_id: str) -> Job | None:
    """Parse job detail HTML into a Job object."""
    def extract(pattern, default=""):
        m = re.search(pattern, html, re.DOTALL)
        return m.group(1).strip() if m else default

    def clean(text):
        return re.sub(r'<[^>]+>', '', text).strip()

    title = clean(extract(r'<h2[^>]*class="[^"]*top-card-layout__title[^"]*"[^>]*>(.*?)</h2>'))
    if not title:
        title = clean(extract(r'<title>(.*?)</title>'))
        title = re.sub(r'\s*\|\s*LinkedIn.*', '', title).strip()

    company = clean(extract(r'<a[^>]*class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)</a>'))
    if not company:
        company = clean(extract(r'<span[^>]*class="[^"]*topcard__flavor[^"]*"[^>]*>(.*?)</span>'))

    location = clean(extract(r'<span[^>]*class="[^"]*topcard__flavor--bullet[^"]*"[^>]*>(.*?)</span>'))
    is_remote = bool(re.search(r'remote', html, re.IGNORECASE))
    if "remote" in location.lower():
        is_remote = True

    if not title:
        return None

    return Job(
        title=title,
        company=company or "Unknown",
        location=location or "Not specified",
        url=f"https://www.linkedin.com/jobs/view/{job_id}/",
        source="linkedin",
        tags=[],
        is_remote=is_remote,
    )


def _headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
