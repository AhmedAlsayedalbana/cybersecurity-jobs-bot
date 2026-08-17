"""
LinkedIn Authenticated Source � v1 (li_at Cookie)
===================================================
 :  li_at cookie   LinkedIn
  scraping   .

li_at  session cookie     LinkedIn.
   cookie:
      IP (    )
      Guest API
     (LinkedIn     )
      proxies  LinkedIn (proxies   )

   li_at:
  1.    linkedin.com
  2.  DevTools  Application  Cookies  linkedin.com
  3.    li_at cookie
  4.   secret: LI_AT  GitHub Actions

      (    )
          .
"""

import logging
import os
import re
import time
import random
from datetime import datetime, timedelta
from models import Job, extract_salary_from_text
from sources.http_utils import _get_linkedin_session, _bootstrap_linkedin
from sources.linkedin_common import FRESH_TPR, linkedin_get_text
import config as _cfg


def _geo_hint_from_search(search: dict) -> str:
    """Derive geo_hint from a search dict that may contain a 'location' key.
    Filters empty/whitespace strings from pattern sets to avoid false positives.
    """
    loc = search.get('location', '').lower()
    if not loc:
        return ''
    _eg = {p for p in _cfg.EGYPT_PATTERNS if p.strip()}
    _gu = {p for p in _cfg.GULF_PATTERNS if p.strip()}
    if any(x in loc for x in _eg):
        return 'egypt'
    if any(x in loc for x in _gu):
        return 'gulf'
    return 'global'

log = logging.getLogger(__name__)

LI_AT = os.environ.get("LI_AT", "").strip()

_BASE_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_DETAIL_URL  = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

#    searches      auth 
_AUTHENTICATED_SEARCHES = [
    # Egypt �    Auth
    {"keywords": "cybersecurity",        "location": "Egypt",               "f_TPR": "r86400",  "count": 25},
    {"keywords": "SOC analyst",          "location": "Cairo, Egypt",        "f_TPR": "r86400",  "count": 25},
    {"keywords": "penetration tester",   "location": "Egypt",               "f_TPR": "r86400",  "count": 15},
    {"keywords": "GRC analyst",          "location": "Egypt",               "f_TPR": "r86400",  "count": 15},
    {"keywords": "security engineer",    "location": "Egypt",               "f_TPR": "r86400",  "count": 15},
    {"keywords": "information security", "location": "Egypt",               "f_TPR": "r86400",  "count": 15},
    # Gulf
    {"keywords": "cybersecurity",        "location": "Saudi Arabia",        "f_TPR": "r86400",  "count": 25},
    {"keywords": "SOC analyst",          "location": "Saudi Arabia",        "f_TPR": "r86400",  "count": 15},
    {"keywords": "cybersecurity",        "location": "Dubai, United Arab Emirates", "f_TPR": "r86400", "count": 25},
    {"keywords": "SOC analyst",          "location": "United Arab Emirates","f_TPR": "r86400",  "count": 15},
    {"keywords": "cybersecurity",        "location": "Qatar",               "f_TPR": "r259200", "count": 10},
    # Remote
    {"keywords": "cybersecurity engineer",   "f_WT": "2", "f_TPR": "r86400", "count": 15},
    {"keywords": "SOC analyst",              "f_WT": "2", "f_TPR": "r86400", "count": 15},
    {"keywords": "penetration tester",       "f_WT": "2", "f_TPR": "r86400", "count": 10},
]


def _page_starts_for_search(index: int) -> list[int]:
    # Deep pagination for top Egypt/Gulf searches.
    if index < 8:
        return [0, 25, 50]
    return [0]


def _parse_detail(html: str, job_id: str, geo_hint: str = "") -> Job | None:
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

    # Extract description for better classification
    desc_raw = extract(r'<div[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</div>', "")
    desc = re.sub(r'<[^>]+>', ' ', desc_raw)
    desc = re.sub(r'\s+', ' ', desc).strip()[:800]
    salary = extract_salary_from_text(f"{title} {desc}")

    posted_date = None
    age_match = re.search(
        r"(\d{1,2})\s*(minute|minutes|min|hour|hours|hr|day|days|d|week|weeks|w)\s+ago",
        html,
        re.IGNORECASE,
    )
    if age_match:
        amount = int(age_match.group(1))
        unit = age_match.group(2).lower()
        now = datetime.now()
        if unit.startswith("min"):
            posted_date = now - timedelta(minutes=amount)
        elif unit.startswith("hour") or unit == "hr":
            posted_date = now - timedelta(hours=amount)
        elif unit.startswith("day") or unit == "d":
            posted_date = now - timedelta(days=amount)
        elif unit.startswith("week") or unit == "w":
            posted_date = now - timedelta(weeks=amount)

    # Extract job type
    job_type = ""
    jt = extract(r'<span[^>]*class="[^"]*workplace-type[^"]*"[^>]*>(.*?)</span>')
    if not jt:
        jt = extract(r'<li[^>]*class="[^"]*job-criteria__item[^"]*"[^>]*>.*?<span[^>]*>(On-site|Remote|Hybrid)</span>', "")
    if jt:
        job_type = clean(jt)

    if not title:
        return None

    return Job(
        title=title,
        company=company or "Unknown",
        location=location or "Not specified",
        url=f"https://www.linkedin.com/jobs/view/{job_id}/",
        source="linkedin_li_at",
        salary=salary,
        description=desc,
        tags=[],
        is_remote=is_remote,
        job_type=job_type,
        posted_date=posted_date,
        geo_hint=geo_hint,
    )


def fetch_linkedin_authenticated() -> list[Job]:
    """
    Fetch LinkedIn jobs using li_at cookie authentication.
    Much less likely to be blocked than anonymous scraping.
    Falls back gracefully if li_at is not set.
    """
    if not LI_AT:
        log.debug("LinkedIn Auth: no LI_AT cookie � skipping authenticated source.")
        return []

    from config import LI_PRIMARY_BUDGET_SECONDS
    BUDGET_SECS = LI_PRIMARY_BUDGET_SECONDS
    _start = time.time()

    jobs     = []
    seen_ids: set[str] = set()
    failures = 0
    MAX_FAIL = 5

    for idx, search in enumerate(_AUTHENTICATED_SEARCHES):
        if time.time() - _start > BUDGET_SECS:
            log.info(f"LinkedIn Auth: budget exhausted after {len(jobs)} jobs � stopping.")
            break
        if failures >= MAX_FAIL:
            log.warning(f"LinkedIn Auth: {failures} failures � stopping.")
            break

        for page_start in _page_starts_for_search(idx):
            params = {
                "keywords": search.get("keywords", ""),
                "start": str(page_start),
                "count": "25",
            }
            if "location" in search:
                params["location"] = search["location"]
            if "f_WT" in search:
                params["f_WT"] = search["f_WT"]
            params["f_TPR"] = FRESH_TPR

            html = linkedin_get_text(_BASE_SEARCH, params=params)
            if not html or len(html) < 200:
                failures += 1
                time.sleep(random.uniform(0.8, 1.5))
                continue
            failures = 0

            job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
            if not job_ids:
                job_ids = re.findall(r'/jobs/view/(\d+)/', html)
            if not job_ids and page_start > 0:
                break

            for job_id in job_ids[:30]:
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                if time.time() - _start > BUDGET_SECS:
                    break
                detail_html = linkedin_get_text(_DETAIL_URL.format(job_id=job_id))
                if not detail_html:
                    continue

                job = _parse_detail(detail_html, job_id, geo_hint=_geo_hint_from_search(search))
                if job:
                    jobs.append(job)

                time.sleep(random.uniform(0.1, 0.25))

            time.sleep(random.uniform(0.2, 0.4))

    log.info(f"LinkedIn Auth: {len(jobs)} jobs fetched (li_at authenticated).")
    return jobs
