"""
intelligence/seniority.py
=========================
Seniority / level classification for job objects.

Public API:
    classify_level(job) → "entry" | "junior" | "mid" | "senior" | "open"
    is_entry_level(job) → bool
"""

from __future__ import annotations

from typing import Any

from intelligence._text import job_description, job_title
from intelligence.patterns import ENTRY_RE, JUNIOR_RE, MID_RE, SENIOR_RE


def classify_level(job: Any) -> str:
    """Return a coarse seniority bucket.

    Checks title first (more reliable), then first 220 chars of description.
    """
    title = job_title(job)
    text = title + " " + job_description(job, limit=220)

    if ENTRY_RE.search(text):
        return "entry"
    if JUNIOR_RE.search(title):
        return "entry"         # junior title → treat as entry-level
    if SENIOR_RE.search(text):
        return "senior"
    if MID_RE.search(text):
        return "mid"
    return "open"


def is_entry_level(job: Any) -> bool:
    return classify_level(job) in {"entry"}
