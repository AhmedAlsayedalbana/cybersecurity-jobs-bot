"""Himalayas — free remote jobs API (no key required). Cybersecurity-focused queries."""

import logging
from models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

BASE = "https://himalayas.app/jobs/api/search"

QUERIES = [
    "cybersecurity engineer",
    "information security engineer",
    "security analyst",
    "penetration tester",
    "ethical hacker",
    "SOC analyst",
    "threat intelligence analyst",
    "incident response analyst",
    "application security engineer",
    "cloud security engineer",
    "devsecops engineer",
    "malware analyst",
    "digital forensics analyst",
    "GRC analyst",
    "security architect",
    "detection engineer",
    "red team operator",
    "network security engineer",
    "security intern",
    "junior security analyst",
]


def fetch_himalayas() -> list[Job]:
    """Fetch cybersecurity jobs from Himalayas."""
    jobs = []
    for q in QUERIES:
        data = get_json(BASE, params={"query": q, "limit": 20})
        if not data or "jobs" not in data:
            continue
        for item in data["jobs"]:
            location = item.get("location", "")
            remote = item.get("timezoneRestriction") is not None or "remote" in location.lower()
            jobs.append(Job(
                title=item.get("title", ""),
                company=item.get("companyName", ""),
                location=location or "Remote",
                url=item.get("applicationLink") or f"https://himalayas.app/jobs/{item.get('slug', '')}",
                source="himalayas",
                salary=_format_salary(item),
                job_type=item.get("employmentType", ""),
                tags=item.get("categories", []) or [],
                is_remote=remote,
            ))
    log.info(f"Himalayas: fetched {len(jobs)} jobs.")
    return jobs


def _format_salary(item: dict) -> str:
    mn = item.get("salaryCurrencyMin")
    mx = item.get("salaryCurrencyMax")
    cur = item.get("salaryCurrency", "USD")
    if mn and mx:
        return f"{cur} {mn:,}–{mx:,}"
    return ""
