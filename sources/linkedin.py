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

# Keep searches focused and minimal to avoid rate-limiting
SEARCHES = [
    # ── Egypt (top priority) ──
    {"keywords": "cybersecurity",        "location": "Egypt",        "f_TPR": "r86400"},
    {"keywords": "information security", "location": "Egypt",        "f_TPR": "r86400"},
    {"keywords": "SOC analyst",          "location": "Egypt",        "f_TPR": "r86400"},
    {"keywords": "penetration tester",   "location": "Egypt",        "f_TPR": "r86400"},
    {"keywords": "security engineer",    "location": "Egypt",        "f_TPR": "r86400"},
    {"keywords": "network security",     "location": "Egypt",        "f_TPR": "r86400"},
    # ── Saudi Arabia ──
    {"keywords": "cybersecurity",        "location": "Saudi Arabia", "f_TPR": "r86400"},
    {"keywords": "SOC analyst",          "location": "Saudi Arabia", "f_TPR": "r86400"},
    {"keywords": "GRC analyst",          "location": "Saudi Arabia", "f_TPR": "r86400"},
    {"keywords": "security engineer",    "location": "Saudi Arabia", "f_TPR": "r86400"},
    # ── UAE ──
    {"keywords": "cybersecurity",        "location": "United Arab Emirates", "f_TPR": "r86400"},
    {"keywords": "security analyst",     "location": "United Arab Emirates", "f_TPR": "r86400"},
    # ── Remote worldwide ──
    {"keywords": "cybersecurity engineer",       "f_WT": "2", "f_TPR": "r86400"},
    {"keywords": "SOC analyst",                  "f_WT": "2", "f_TPR": "r86400"},
    {"keywords": "penetration tester",           "f_WT": "2", "f_TPR": "r86400"},
    {"keywords": "threat intelligence analyst",  "f_WT": "2", "f_TPR": "r86400"},
    {"keywords": "application security engineer","f_WT": "2", "f_TPR": "r86400"},
    {"keywords": "cloud security engineer",      "f_WT": "2", "f_TPR": "r86400"},
    {"keywords": "devsecops",                    "f_WT": "2", "f_TPR": "r86400"},
    {"keywords": "red team",                     "f_WT": "2", "f_TPR": "r86400"},
]


def fetch_linkedin() -> list[Job]:
    """Fetch cybersecurity jobs from LinkedIn guest API."""
    jobs = []
    seen_ids: set[str] = set()
    consecutive_failures = 0

    for search in SEARCHES:
        # Stop early if LinkedIn is blocking us
        if consecutive_failures >= 3:
            log.warning("LinkedIn: too many consecutive failures — stopping early.")
            break

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

        html = get_text(SEARCH_URL, params=params, headers=_headers())
        if not html:
            consecutive_failures += 1
            time.sleep(2)
            continue

        consecutive_failures = 0

        # Extract job IDs from search results page
        job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        if not job_ids:
            job_ids = re.findall(r'"jobPostingId":(\d+)', html)
        if not job_ids:
            job_ids = re.findall(r'/jobs/view/(\d+)/', html)

        for job_id in job_ids[:5]:  # max 5 per search to avoid hammering
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
            time.sleep(0.5)   # polite delay

        time.sleep(1)  # delay between searches

    log.info(f"LinkedIn: fetched {len(jobs)} jobs.")
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
