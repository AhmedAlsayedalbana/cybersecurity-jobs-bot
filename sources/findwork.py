"""Findwork.dev — API for software dev jobs. Cybersecurity-focused queries."""

import logging
from models import Job
from sources.http_utils import get_json
from config import FINDWORK_API_KEY

log = logging.getLogger(__name__)

URL = "https://findwork.dev/api/jobs/"

SEARCHES = [
    "cybersecurity", "security engineer", "security analyst",
    "penetration tester", "SOC analyst", "threat intelligence",
    "incident response", "application security", "devsecops",
    "cloud security", "malware analyst", "digital forensics",
    "GRC analyst", "security architect", "detection engineer",
    "red team", "network security engineer",
]


def fetch_findwork() -> list[Job]:
    """Fetch cybersecurity remote jobs from Findwork.dev."""
    if not FINDWORK_API_KEY:
        log.warning("Findwork: API key not set — skipping.")
        return []

    headers = {"Authorization": f"Token {FINDWORK_API_KEY}"}
    jobs = []

    for search in SEARCHES:
        data = get_json(URL, params={"search": search, "remote": "true"}, headers=headers)
        if not data or "results" not in data:
            continue
        for item in data["results"]:
            jobs.append(Job(
                title=item.get("role", ""),
                company=item.get("company_name", ""),
                location=item.get("location", "Remote"),
                url=item.get("url", ""),
                source="findwork",
                salary="",
                job_type=item.get("employment_type", ""),
                tags=item.get("keywords", []) or [],
                is_remote=item.get("remote", False),
            ))
    log.info(f"Findwork: fetched {len(jobs)} jobs.")
    return jobs
