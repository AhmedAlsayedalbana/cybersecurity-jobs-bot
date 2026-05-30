"""Remotive � remote jobs API. Using devops-sysadmin category (most relevant for security)."""

import logging
from datetime import datetime
from models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

BASE = "https://remotive.com/api/remote-jobs"
# devops-sysadmin is the closest category on Remotive to security roles
CATEGORIES = ["software-dev", "devops-sysadmin"]


def fetch_remotive() -> list[Job]:
    """Fetch jobs from Remotive. Keyword filter in config will keep only security jobs."""
    jobs = []
    for cat in CATEGORIES:
        data = get_json(BASE, params={"category": cat, "limit": 50})
        if not data or "jobs" not in data:
            continue
        for item in data["jobs"]:
            posted_date = None
            raw_date = item.get("publication_date") or item.get("created_at") or ""
            if raw_date:
                try:
                    posted_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError:
                    posted_date = None
            jobs.append(Job(
                title=item.get("title", ""),
                company=item.get("company_name", ""),
                location=item.get("candidate_required_location", "Anywhere"),
                url=item.get("url", ""),
                source="remotive",
                salary=item.get("salary", ""),
                job_type=item.get("job_type", "").replace("_", " ").title(),
                tags=[item.get("category", "")],
                is_remote=True,
                posted_date=posted_date,
            ))
    log.info(f"Remotive: fetched {len(jobs)} jobs.")
    return jobs
