"""Adzuna — job aggregator API (free tier, needs app_id + app_key).
Cybersecurity-focused searches.
"""

import logging
from models import Job
from sources.http_utils import get_json
from config import ADZUNA_APP_ID, ADZUNA_APP_KEY

log = logging.getLogger(__name__)

BASE = "https://api.adzuna.com/v1/api/jobs"

SEARCHES = [
    {"country": "gb", "what": "cybersecurity engineer", "where": ""},
    {"country": "us", "what": "cybersecurity engineer remote", "where": ""},
    {"country": "us", "what": "penetration tester remote", "where": ""},
    {"country": "us", "what": "SOC analyst remote", "where": ""},
    {"country": "us", "what": "information security analyst remote", "where": ""},
    {"country": "gb", "what": "penetration tester", "where": ""},
    {"country": "gb", "what": "security analyst", "where": ""},
    {"country": "de", "what": "cybersecurity engineer remote", "where": ""},
    {"country": "au", "what": "cybersecurity engineer remote", "where": ""},
]


def fetch_adzuna() -> list[Job]:
    """Fetch cybersecurity jobs from Adzuna."""
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        log.warning("Adzuna: credentials not set — skipping.")
        return []

    jobs = []
    for search in SEARCHES:
        country = search["country"]
        url = f"{BASE}/{country}/search/1"
        params = {
            "app_id": ADZUNA_APP_ID,
            "app_key": ADZUNA_APP_KEY,
            "what": search["what"],
            "results_per_page": 20,
            "content-type": "application/json",
            "sort_by": "date",
        }
        if search["where"]:
            params["where"] = search["where"]

        data = get_json(url, params=params)
        if not data or "results" not in data:
            continue

        for item in data["results"]:
            location_parts = []
            loc = item.get("location", {})
            if loc.get("display_name"):
                location_parts.append(loc["display_name"])
            location = ", ".join(location_parts) or country.upper()

            salary = ""
            if item.get("salary_min") and item.get("salary_max"):
                salary = f"£{item['salary_min']:,.0f}–£{item['salary_max']:,.0f}"

            desc = (item.get("description") or "").lower()
            is_remote = "remote" in desc or "remote" in item.get("title", "").lower()

            jobs.append(Job(
                title=item.get("title", ""),
                company=item.get("company", {}).get("display_name", ""),
                location=location,
                url=item.get("redirect_url", ""),
                source="adzuna",
                salary=salary,
                tags=[],
                is_remote=is_remote,
            ))

    log.info(f"Adzuna: fetched {len(jobs)} jobs.")
    return jobs
