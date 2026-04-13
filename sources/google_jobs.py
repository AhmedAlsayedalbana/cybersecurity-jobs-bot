"""
Google Jobs & Smart Aggregator — V12 (Professional System)
Focused on Egypt & Gulf cybersecurity roles with silent error handling.
"""

import logging
import os
from models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

GOOGLE_JOBS_SEARCHES = [
    # Egypt focused
    {"q": "cybersecurity jobs Egypt",           "location": "Egypt"},
    {"q": "SOC analyst jobs Cairo",             "location": "Egypt"},
    {"q": "penetration tester jobs Egypt",      "location": "Egypt"},
    {"q": "security engineer jobs Egypt",       "location": "Egypt"},
    {"q": "information security jobs Egypt",    "location": "Egypt"},
    {"q": "junior cybersecurity jobs Egypt",    "location": "Egypt"},
    # Saudi
    {"q": "cybersecurity jobs Saudi Arabia",    "location": "Saudi Arabia"},
    {"q": "SOC analyst Riyadh",                 "location": "Saudi Arabia"},
    {"q": "security engineer Saudi Arabia",     "location": "Saudi Arabia"},
    # UAE
    {"q": "cybersecurity jobs Dubai",           "location": "UAE"},
    {"q": "security analyst UAE",               "location": "UAE"},
]


def _fetch_via_serpapi():
    """Use SerpAPI to get Google Jobs results (Silent if no key)."""
    if not SERPAPI_KEY:
        return []

    jobs = []
    seen_urls = set()

    for search in GOOGLE_JOBS_SEARCHES:
        params = {
            "engine": "google_jobs",
            "q": search["q"],
            "location": search.get("location", ""),
            "api_key": SERPAPI_KEY,
            "hl": "en",
            "gl": "eg" if "Egypt" in search.get("location", "") else "us",
        }
        try:
            data = get_json("https://serpapi.com/search", params=params, headers=HEADERS)
            if not data or "jobs_results" not in data:
                continue

            for item in data["jobs_results"]:
                url_job = ""
                related = item.get("related_links", [])
                if related:
                    url_job = related[0].get("link", "")
                if not url_job:
                    url_job = "https://www.google.com/search?q=" + search["q"].replace(" ", "+") + "&ibp=htl;jobs"

                if url_job in seen_urls:
                    continue
                seen_urls.add(url_job)

                jobs.append(Job(
                    title=item.get("title", ""),
                    company=item.get("company_name", "Unknown"),
                    location=item.get("location", search.get("location", "")),
                    url=url_job,
                    source="google_jobs",
                    salary=item.get("salary", ""),
                    job_type=", ".join(item.get("detected_extensions", {}).get("schedule_type", [])) if item.get("detected_extensions") else "",
                    tags=["google_jobs", search.get("location", "")],
                    is_remote="remote" in item.get("location", "").lower(),
                    description=item.get("description", "")[:300],
                ))
        except:
            continue

    return jobs


def _fetch_adzuna_mena():
    """Adzuna MENA — Egypt and Gulf searches (Silent if no keys)."""
    from config import ADZUNA_APP_ID, ADZUNA_APP_KEY
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return []

    jobs = []
    searches = [
        ("eg", "cybersecurity", "Egypt"),
        ("eg", "information security", "Egypt"),
        ("ae", "cybersecurity", "UAE"),
        ("sa", "cybersecurity", "Saudi Arabia"),
    ]

    for country_code, query, location in searches:
        url = (
            f"https://api.adzuna.com/v1/api/jobs/{country_code}/search/1"
            f"?app_id={ADZUNA_APP_ID}&app_key={ADZUNA_APP_KEY}"
            f"&results_per_page=15&what={query.replace(' ', '+')}&sort_by=date"
        )
        try:
            data = get_json(url, headers=HEADERS)
            if not data or "results" not in data:
                continue
            for item in data["results"]:
                jobs.append(Job(
                    title=item.get("title", ""),
                    company=item.get("company", {}).get("display_name", "Unknown"),
                    location=item.get("location", {}).get("display_name", location),
                    url=item.get("redirect_url", ""),
                    source="adzuna_mena",
                    tags=["adzuna", location],
                    is_remote="remote" in item.get("title", "").lower(),
                ))
        except:
            continue

    return jobs


def fetch_google_jobs():
    """Aggregate Google Jobs + fallbacks silently."""
    all_jobs = []
    for fn in [_fetch_via_serpapi, _fetch_adzuna_mena]:
        try:
            all_jobs.extend(fn())
        except:
            pass
    return all_jobs
