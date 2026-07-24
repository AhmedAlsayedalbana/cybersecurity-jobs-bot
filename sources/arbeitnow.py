"""Arbeitnow � free job board API."""

import logging
from datetime import datetime
from models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

URL = "https://www.arbeitnow.com/api/job-board-api"


def fetch_arbeitnow() -> list[Job]:
    """Fetch jobs from Arbeitnow."""
    data = get_json(URL)
    if not data or "data" not in data:
        log.warning("Arbeitnow: no data.")
        return []

    jobs = []
    for item in data["data"]:
        is_remote = item.get("remote", False)
        tags = item.get("tags", []) or []
        posted_date = None
        created_at = item.get("created_at")
        if created_at:
            try:
                posted_date = datetime.fromtimestamp(int(created_at))
            except (TypeError, ValueError, OSError):
                try:
                    posted_date = datetime.fromisoformat(str(created_at).replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError:
                    posted_date = None

        jobs.append(Job(
            title=item.get("title", ""),
            company=item.get("company_name", ""),
            location=item.get("location", ""),
            url=item.get("url", ""),
            source="arbeitnow",
            salary="",
            job_type="",
            tags=tags,
            is_remote=is_remote,
            posted_date=posted_date,
        ))
    log.info(f"Arbeitnow: fetched {len(jobs)} jobs.")
    return jobs
