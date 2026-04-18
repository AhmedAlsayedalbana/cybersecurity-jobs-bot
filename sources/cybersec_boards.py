"""
Cybersecurity-specific job boards — v27 (clean single version)

CONFIRMED WORKING:
  ✅ Bugcrowd Greenhouse: ~4 jobs

CONFIRMED DEAD (removed):
  ❌ CyberSecJobs RSS — HTTP 404
  ❌ HackerOne careers — 0 jobs
  ❌ BuiltIn — 0 jobs
"""

import logging
from models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
    )
}

SEC_TITLES = [
    "security", "cyber", "soc", "pentest", "threat", "vulnerability",
    "grc", "dfir", "appsec", "devsecops", "cloud security", "infosec",
    "malware", "forensic", "red team", "blue team", "incident",
    "detection", "identity", "iam", "privacy",
]


def _fetch_bugcrowd() -> list:
    """Bugcrowd Greenhouse board — confirmed working, ~4 jobs."""
    jobs = []
    data = get_json(
        "https://api.greenhouse.io/v1/boards/bugcrowd/jobs?content=true",
        headers=_H
    )
    if not data or "jobs" not in data:
        log.info("Bugcrowd: 0 jobs")
        return jobs
    for item in data["jobs"]:
        title   = item.get("title", "")
        job_url = item.get("absolute_url", "")
        if not any(k in title.lower() for k in SEC_TITLES):
            continue
        if not job_url:
            continue
        loc      = item.get("location", {})
        location = loc.get("name", "") if isinstance(loc, dict) else ""
        jobs.append(Job(
            title=title, company="Bugcrowd",
            location=location or "Remote",
            url=job_url, source="cybersec_boards",
            tags=["bugcrowd", "cybersecurity"],
            is_remote="remote" in location.lower(),
        ))
    log.info(f"Bugcrowd: {len(jobs)} jobs")
    return jobs


def fetch_cybersec_boards() -> list:
    """Only Bugcrowd is confirmed working."""
    try:
        return _fetch_bugcrowd()
    except Exception as e:
        log.warning(f"cybersec_boards: {e}")
        return []
