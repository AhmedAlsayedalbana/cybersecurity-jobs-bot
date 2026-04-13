"""
Job Dataclass & Filtering Logic — V12 (Professional System)
"""

import re
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import config

log = logging.getLogger(__name__)

@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    source: str
    description: str = ""
    salary: str = ""
    job_type: str = ""
    posted_date: Optional[datetime] = None
    tags: list = field(default_factory=list)
    is_remote: bool = False
    score: int = 0
    original_source: str = ""

    @property
    def unique_id(self) -> str:
        """Unique ID for deduplication."""
        clean_url = re.sub(r'[?&]utm_.*', '', self.url)
        return f"{self.title.lower()}|{self.company.lower()}|{clean_url}"


# =========================
# 🔥 FIX (المشكلة كانت هنا)
# =========================
def _flatten_tags(tags: list) -> str:
    """Convert tag list into a searchable string."""
    try:
        return " ".join(str(t) for t in (tags or []))
    except Exception:
        return ""


def _is_in_egypt(location: str) -> bool:
    loc = location.lower()
    return any(p in loc for p in config.EGYPT_PATTERNS)


def _is_in_gulf(location: str) -> bool:
    loc = location.lower()
    return any(p in loc for p in config.GULF_PATTERNS)


def _is_remote(location: str, title: str = "") -> bool:
    text = (location + " " + title).lower()
    return any(p in text for p in config.REMOTE_PATTERNS)


def passes_cyber_filter(title: str) -> bool:
    title = title.lower()

    # 1. Must have at least one include keyword
    if not any(k in title for k in config.INCLUDE_KEYWORDS):
        return False

    # 2. Must NOT have any exclude keywords
    if any(k in title for k in config.EXCLUDE_KEYWORDS):
        return False

    return True


def filter_jobs(jobs: list[Job]) -> list[Job]:
    """Filter jobs by cybersec relevance and location."""
    filtered = []

    for job in jobs:
        if not job.title or not job.url:
            continue

        # 1. Cybersec Relevance
        if not passes_cyber_filter(job.title):
            continue

        # 2. Location Filter (Egypt, Gulf, or Remote only)
        is_eg = _is_in_egypt(job.location)
        is_gulf = _is_in_gulf(job.location)
        is_rem = _is_remote(job.location, job.title) or job.is_remote

        if is_eg or is_gulf or is_rem:
            # Normalize location
            if is_eg:
                job.location = "Egypt 🇪🇬"
            elif is_gulf:
                job.location = "Gulf 🌙"
            elif is_rem:
                job.is_remote = True

            filtered.append(job)

    log.info(f"Filtered {len(jobs)} jobs down to {len(filtered)}")
    return filtered
