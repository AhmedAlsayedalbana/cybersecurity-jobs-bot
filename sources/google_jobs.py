"""
Google Jobs scraper — uses SerpAPI or direct scraping fallback.
Catches jobs from small sites that have no API or RSS feed.
Focused on Egypt & Gulf cybersecurity roles.
"""

import logging
import re
import json
from models import Job
from sources.http_utils import get_text, get_json
import os

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
    {"q": "cybersecurity jobs Egypt",           "location": "Egypt",                        "gl": "eg"},
    {"q": "SOC analyst jobs Cairo",             "location": "Cairo, Egypt",                 "gl": "eg"},
    {"q": "penetration tester jobs Egypt",      "location": "Egypt",                        "gl": "eg"},
    {"q": "security engineer jobs Egypt",       "location": "Egypt",                        "gl": "eg"},
    {"q": "junior cybersecurity jobs Egypt",    "location": "Egypt",                        "gl": "eg"},
    # Saudi
    {"q": "cybersecurity jobs Saudi Arabia",    "location": "Riyadh, Saudi Arabia",         "gl": "sa"},
    {"q": "SOC analyst Riyadh",                 "location": "Riyadh, Saudi Arabia",         "gl": "sa"},
    # UAE
    {"q": "cybersecurity jobs Dubai",           "location": "Dubai, United Arab Emirates",  "gl": "ae"},
    {"q": "security analyst Dubai",             "location": "Dubai, United Arab Emirates",  "gl": "ae"},
    # Other Gulf
    {"q": "cybersecurity jobs Qatar",           "location": "Doha, Qatar",                  "gl": "qa"},
]


def _fetch_via_serpapi():
    """Use SerpAPI to get Google Jobs results (requires SERPAPI_KEY)."""
    if not SERPAPI_KEY:
        return []

    jobs = []
    seen_urls = set()
    _first_request_done = False

    for search in GOOGLE_JOBS_SEARCHES:
        params = {
            "engine": "google_jobs",
            "q": search["q"],
            "location": search.get("location", ""),
            "api_key": SERPAPI_KEY,
            "hl": "en",
            "gl": search.get("gl", "us"),
        }
        data = get_json("https://serpapi.com/search", params=params, headers=HEADERS)
        # If the very first request fails, the API key is invalid/expired — abort early
        if not _first_request_done:
            _first_request_done = True
            if not data or "jobs_results" not in data:
                log.warning("SerpAPI: first request failed — skipping remaining searches")
                break
        if not data or "jobs_results" not in data:
            continue

        for item in data["jobs_results"]:
            url_job = ""
            # Try to get apply link
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

    log.info("Google Jobs (SerpAPI): " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_via_jooble_arabic():
    """
    Fallback: Use Jooble with Arabic-market focused queries.
    Jooble aggregates from many small sites Google also covers.
    """
    from config import JOOBLE_API_KEY
    if not JOOBLE_API_KEY:
        return []

    jobs = []
    searches = [
        {"keywords": "cybersecurity", "location": "Egypt"},
        {"keywords": "SOC analyst", "location": "Egypt"},
        {"keywords": "penetration tester", "location": "Egypt"},
        {"keywords": "security engineer", "location": "Saudi Arabia"},
        {"keywords": "cybersecurity", "location": "Dubai"},
        {"keywords": "information security", "location": "UAE"},
        {"keywords": "security analyst", "location": "Qatar"},
    ]

    for s in searches:
        data = get_json(
            "https://jooble.org/api/" + JOOBLE_API_KEY,
            headers=HEADERS,
        )
        # Jooble uses POST — handle differently
        import requests as _req
        try:
            resp = _req.post(
                "https://jooble.org/api/" + JOOBLE_API_KEY,
                json={"keywords": s["keywords"], "location": s["location"]},
                timeout=10,
            )
            data = resp.json() if resp.status_code == 200 else None
        except Exception:
            continue

        if not data:
            continue
        for item in data.get("jobs", []):
            jobs.append(Job(
                title=item.get("title", ""),
                company=item.get("company", "Unknown"),
                location=item.get("location", s["location"]),
                url=item.get("link", ""),
                source="jooble_arabic",
                salary=item.get("salary", ""),
                tags=["jooble", s["location"]],
                is_remote="remote" in item.get("location", "").lower(),
            ))

    log.info("Jooble Arabic: " + str(len(jobs)) + " jobs")
    return jobs


def _fetch_adzuna_mena():
    """Adzuna MENA — Egypt and Gulf searches."""
    from config import ADZUNA_APP_ID, ADZUNA_APP_KEY
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return []

    jobs = []
    searches = [
        ("eg", "cybersecurity", "Egypt"),
        ("eg", "SOC analyst", "Egypt"),
        ("eg", "penetration tester", "Egypt"),
        ("eg", "security engineer", "Egypt"),
        ("ae", "cybersecurity", "UAE"),
        ("ae", "security engineer", "UAE"),
        ("ae", "SOC analyst", "UAE"),
    ]

    for country_code, query, location in searches:
        url = (
            "https://api.adzuna.com/v1/api/jobs/" + country_code + "/search/1"
            "?app_id=" + ADZUNA_APP_ID +
            "&app_key=" + ADZUNA_APP_KEY +
            "&results_per_page=20&what=" + query.replace(" ", "+") +
            "&sort_by=date"
        )
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
                salary=str(item.get("salary_min", "")) + "-" + str(item.get("salary_max", "")) if item.get("salary_min") else "",
                tags=["adzuna", location],
                is_remote="remote" in item.get("title", "").lower(),
            ))

    log.info("Adzuna MENA: " + str(len(jobs)) + " jobs")
    return jobs


def fetch_google_jobs():
    """Aggregate Google Jobs + fallbacks."""
    all_jobs = []
    for fn in [_fetch_via_serpapi, _fetch_adzuna_mena]:
        try:
            all_jobs.extend(fn())
        except Exception as e:
            log.warning("google_jobs sub-fetcher " + fn.__name__ + " failed: " + str(e))
    return all_jobs
