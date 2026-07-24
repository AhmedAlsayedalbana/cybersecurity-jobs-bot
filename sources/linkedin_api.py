"""
LinkedIn Official API Source � v1
===================================
 LinkedIn Partner API  (  LINKEDIN_ACCESS_TOKEN )
 LinkedIn Job Search API  RapidAPI (RAPIDAPI_KEY).

GENIUS IDEA �  LinkedIn Job Search :
1. LinkedIn Partner API ( �  partner access)
2. JSearch API on RapidAPI (real LinkedIn data, no scraping)
3. LinkedIn Guest API  li_at cookie (no ban, authenticated)
4. Adzuna API (aggregates LinkedIn + other sources)

    100%   API   scraping.
"""

import logging
import time
import os
from models import Job
from linkedin_url_utils import canonicalize_job_url
from sources.http_utils import get_json

log = logging.getLogger(__name__)

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
JSEARCH_HOST = "jsearch.p.rapidapi.com"


def _jsearch_fetch(query: str, location: str = "", num_pages: int = 2) -> list[Job]:
    """
    JSearch API � real LinkedIn + Indeed + Glassdoor data via RapidAPI.
    Returns actual LinkedIn job IDs with full details.
    """
    if not RAPIDAPI_KEY:
        return []

    jobs = []
    seen_ids = set()
    q = f"{query} {location}".strip() if location else query

    for page in range(1, num_pages + 1):
        data = get_json(
            f"https://{JSEARCH_HOST}/search",
            params={"query": q, "page": str(page), "num_pages": "1", "date_posted": "today"},
            headers={
                "X-RapidAPI-Key":  RAPIDAPI_KEY,
                "X-RapidAPI-Host": JSEARCH_HOST,
            },
        )
        if not data or "data" not in data:
            break

        for item in data.get("data", []):
            job_id = item.get("job_id", "") or item.get("job_apply_link", "")
            if not job_id or job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            title   = item.get("job_title", "")
            company = item.get("employer_name", "")
            loc     = item.get("job_city", "") or item.get("job_country", "")
            if item.get("job_state"):
                loc = f"{item['job_city']}, {item['job_state']}"
            url = item.get("job_apply_link", "") or item.get("job_google_link", "")

            # Prefer LinkedIn URL
            linkedin_url = ""
            for link in item.get("apply_options", []):
                if "linkedin.com" in link.get("apply_link", ""):
                    linkedin_url = link["apply_link"]
                    break
            if linkedin_url:
                url = linkedin_url

            if not title or not url:
                continue

            desc = item.get("job_description", "")
            is_remote = item.get("job_is_remote", False)
            job_type  = item.get("job_employment_type", "")

            # Posted date
            posted_date = None
            posted_ts = item.get("job_posted_at_timestamp")
            if posted_ts:
                from datetime import datetime
                try:
                    posted_date = datetime.fromtimestamp(posted_ts)
                except Exception:
                    pass

            # Salary
            salary = ""
            min_sal = item.get("job_min_salary")
            max_sal = item.get("job_max_salary")
            sal_cur = item.get("job_salary_currency", "")
            sal_per = item.get("job_salary_period", "")
            if min_sal and max_sal:
                salary = f"{min_sal:,.0f}�{max_sal:,.0f} {sal_cur} / {sal_per}"
            elif min_sal:
                salary = f"{min_sal:,.0f}+ {sal_cur} / {sal_per}"

            jobs.append(Job(
                title=title,
                company=company,
                location=loc,
                url=canonicalize_job_url(url),
                source="jsearch",
                description=desc[:500],
                is_remote=is_remote,
                job_type=job_type,
                salary=salary,
                posted_date=posted_date,
                original_source="JSearch (LinkedIn/Indeed)",
            ))

        time.sleep(1.0)

    return jobs


def fetch_jsearch_linkedin() -> list[Job]:
    """
    Fetch cybersecurity jobs from JSearch API (aggregates LinkedIn + Indeed).
    High priority Egypt + Gulf searches.
    """
    if not RAPIDAPI_KEY:
        log.info("JSearch: no RAPIDAPI_KEY � skipping.")
        return []

    searches = [
        # Egypt
        ("cybersecurity Egypt", ""),
        ("SOC analyst Egypt", ""),
        ("penetration tester Egypt", ""),
        ("security engineer Cairo", ""),
        ("information security Egypt", ""),
        # Gulf
        ("cybersecurity Saudi Arabia", ""),
        ("SOC analyst Dubai", ""),
        ("security engineer UAE", ""),
        # Remote
        ("cybersecurity remote", ""),
        ("SOC analyst remote", ""),
    ]

    all_jobs = []
    for query, location in searches:
        jobs = _jsearch_fetch(query, location, num_pages=1)
        all_jobs.extend(jobs)
        log.debug(f"JSearch: '{query}'  {len(jobs)} jobs")
        time.sleep(0.5)

    log.info(f"JSearch LinkedIn: {len(all_jobs)} total jobs")
    return all_jobs
