"""JSearch (RapidAPI) — aggregates LinkedIn, Indeed, Glassdoor, etc.
Cybersecurity-focused searches only.
"""

import logging
from models import Job
from sources.http_utils import get_json
from config import RAPIDAPI_KEY

log = logging.getLogger(__name__)

URL = "https://jsearch.p.rapidapi.com/search"

_R = {"remote_jobs_only": "true", "num_pages": "1"}
_L = {"num_pages": "1"}

SEARCHES = [
    # ── Remote worldwide ──
    {"query": "cybersecurity engineer remote", **_R},
    {"query": "information security engineer remote", **_R},
    {"query": "security analyst remote", **_R},
    {"query": "penetration tester remote", **_R},
    {"query": "ethical hacker remote", **_R},
    {"query": "SOC analyst remote", **_R},
    {"query": "threat intelligence analyst remote", **_R},
    {"query": "incident response analyst remote", **_R},
    {"query": "application security engineer remote", **_R},
    {"query": "cloud security engineer remote", **_R},
    {"query": "devsecops engineer remote", **_R},
    {"query": "malware analyst remote", **_R},
    {"query": "digital forensics analyst remote", **_R},
    {"query": "GRC analyst remote", **_R},
    {"query": "security architect remote", **_R},
    {"query": "detection engineer remote", **_R},
    {"query": "red team operator remote", **_R},
    {"query": "vulnerability researcher remote", **_R},
    {"query": "cyber threat intelligence remote", **_R},
    {"query": "network security engineer remote", **_R},
    {"query": "security intern remote", **_R},
    # ── Egypt ──
    {"query": "cybersecurity in Egypt", **_L},
    {"query": "information security in Egypt", **_L},
    {"query": "security analyst in Egypt", **_L},
    {"query": "SOC analyst in Egypt", **_L},
    {"query": "penetration tester in Egypt", **_L},
    {"query": "network security engineer in Egypt", **_L},
    {"query": "security engineer in Cairo, Egypt", **_L},
    {"query": "security intern in Egypt", **_L},
    {"query": "junior cybersecurity in Egypt", **_L},
    # ── Saudi Arabia ──
    {"query": "cybersecurity in Saudi Arabia", **_L},
    {"query": "information security in Saudi Arabia", **_L},
    {"query": "security analyst in Saudi Arabia", **_L},
    {"query": "SOC analyst in Riyadh, Saudi Arabia", **_L},
    {"query": "penetration tester in Saudi Arabia", **_L},
    {"query": "cloud security engineer in Saudi Arabia", **_L},
    {"query": "GRC analyst in Saudi Arabia", **_L},
    {"query": "security engineer in Jeddah, Saudi Arabia", **_L},
    {"query": "network security in Saudi Arabia", **_L},
    {"query": "CISO in Saudi Arabia", **_L},
]

PUBLISHER_MAP = {
    "linkedin.com": "LinkedIn",
    "indeed.com": "Indeed",
    "glassdoor.com": "Glassdoor",
    "ziprecruiter.com": "ZipRecruiter",
    "monster.com": "Monster",
}


def fetch_jsearch() -> list[Job]:
    """Fetch cybersecurity jobs from JSearch across multiple queries."""
    if not RAPIDAPI_KEY:
        log.warning("JSearch: RAPIDAPI_KEY not set — skipping.")
        return []

    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }

    jobs = []
    for params in SEARCHES:
        data = get_json(URL, params=params, headers=headers)
        if not data or "data" not in data:
            continue
        for item in data["data"]:
            publisher = item.get("job_publisher", "")
            original_source = _resolve_publisher(publisher)

            salary = ""
            if item.get("job_min_salary") and item.get("job_max_salary"):
                cur = item.get("job_salary_currency", "USD")
                salary = f"{cur} {item['job_min_salary']:,.0f}–{item['job_max_salary']:,.0f}"

            location = item.get("job_city", "")
            if item.get("job_state"):
                location = f"{location}, {item['job_state']}" if location else item["job_state"]
            if item.get("job_country"):
                location = f"{location}, {item['job_country']}" if location else item["job_country"]

            jobs.append(Job(
                title=item.get("job_title", ""),
                company=item.get("employer_name", ""),
                location=location or "Not specified",
                url=item.get("job_apply_link", ""),
                source="jsearch",
                salary=salary,
                job_type=(item.get("job_employment_type") or "").replace("FULLTIME", "Full Time")
                    .replace("PARTTIME", "Part Time").replace("CONTRACTOR", "Contract")
                    .replace("INTERN", "Internship"),
                tags=[],
                is_remote=item.get("job_is_remote", False),
                original_source=original_source,
            ))
    log.info(f"JSearch: fetched {len(jobs)} jobs.")
    return jobs


def _resolve_publisher(publisher: str) -> str:
    pub = publisher.lower()
    for domain, name in PUBLISHER_MAP.items():
        if domain in pub:
            return name
    return publisher or "JSearch"
