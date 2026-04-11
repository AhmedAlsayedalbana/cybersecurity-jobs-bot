"""Jooble — global job search API (POST-based, free key).
Cybersecurity-focused searches.
"""

import logging
from models import Job
from sources.http_utils import post_json
from config import JOOBLE_API_KEY

log = logging.getLogger(__name__)

BASE = "https://jooble.org/api"

SEARCHES = [
    # Remote
    {"keywords": "cybersecurity engineer", "location": "remote"},
    {"keywords": "information security analyst", "location": "remote"},
    {"keywords": "penetration tester", "location": "remote"},
    {"keywords": "SOC analyst", "location": "remote"},
    {"keywords": "threat intelligence analyst", "location": "remote"},
    {"keywords": "incident response analyst", "location": "remote"},
    {"keywords": "application security engineer", "location": "remote"},
    {"keywords": "cloud security engineer", "location": "remote"},
    {"keywords": "devsecops engineer", "location": "remote"},
    {"keywords": "malware analyst", "location": "remote"},
    {"keywords": "red team operator", "location": "remote"},
    {"keywords": "GRC analyst", "location": "remote"},
    {"keywords": "security architect", "location": "remote"},
    # Egypt
    {"keywords": "cybersecurity", "location": "Egypt"},
    {"keywords": "information security", "location": "Cairo, Egypt"},
    {"keywords": "security analyst", "location": "Egypt"},
    {"keywords": "SOC analyst", "location": "Egypt"},
    {"keywords": "penetration tester", "location": "Egypt"},
    {"keywords": "network security", "location": "Egypt"},
    {"keywords": "security intern", "location": "Egypt"},
    # Saudi Arabia
    {"keywords": "cybersecurity", "location": "Saudi Arabia"},
    {"keywords": "information security", "location": "Riyadh, Saudi Arabia"},
    {"keywords": "security analyst", "location": "Saudi Arabia"},
    {"keywords": "SOC analyst", "location": "Saudi Arabia"},
    {"keywords": "cloud security", "location": "Saudi Arabia"},
    {"keywords": "GRC analyst", "location": "Saudi Arabia"},
    {"keywords": "CISO", "location": "Saudi Arabia"},
    {"keywords": "penetration tester", "location": "Saudi Arabia"},
]


def fetch_jooble() -> list[Job]:
    """Fetch cybersecurity jobs from Jooble."""
    if not JOOBLE_API_KEY:
        log.warning("Jooble: JOOBLE_API_KEY not set — skipping.")
        return []

    url = f"{BASE}/{JOOBLE_API_KEY}"
    jobs = []

    for search in SEARCHES:
        payload = {
            "keywords": search["keywords"],
            "location": search["location"],
            "resultonpage": 10,
        }
        data = post_json(url, payload)
        if not data or "jobs" not in data:
            continue

        for item in data["jobs"]:
            location = item.get("location", "")
            is_remote = "remote" in location.lower() or "remote" in item.get("title", "").lower()

            salary = item.get("salary", "")

            jobs.append(Job(
                title=item.get("title", ""),
                company=item.get("company", ""),
                location=location or "Not specified",
                url=item.get("link", ""),
                source="jooble",
                salary=salary,
                tags=[],
                is_remote=is_remote,
            ))

    log.info(f"Jooble: fetched {len(jobs)} jobs.")
    return jobs
