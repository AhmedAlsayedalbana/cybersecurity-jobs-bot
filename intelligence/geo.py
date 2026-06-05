"""
intelligence/geo.py
===================
Geographic classification for job objects.

Public API:
    classify_geo(job)      → "egypt" | "ksa" | "gulf_other" | "remote" | "global"
    classify_location(job) → "egypt" | "gulf" | "global"
    is_remote_job(job)     → bool
"""

from __future__ import annotations

from typing import Any

import config
from intelligence._text import has_any, job_description, job_full_text, job_tags, norm
from intelligence.patterns import GULF_OTHER_PATTERNS, KSA_PATTERNS

_REMOTE_PATTERNS: frozenset[str] = frozenset(config.REMOTE_PATTERNS)
_EGYPT_ARABIC_PATTERNS: frozenset[str] = frozenset({
    "مصر", "القاهرة", "الجيزة", "الإسكندرية", "اسكندرية", "الإسكندريه",
    "اسكندريه", "الاسكندرية", "الاسكندريه", "القاهره", "الجيزه",
})


def is_remote_job(job: Any) -> bool:
    if getattr(job, "is_remote", False):
        return True
    return has_any(_REMOTE_PATTERNS, job_full_text(job, desc_limit=300))


def classify_geo(job: Any) -> str:
    """Return the canonical geo bucket for a job.

    Priority order (most authoritative → least):
        1. Location string
        2. Tag cloud
        3. geo_hint attribute (set by source connector)
        4. Description head (first 400 chars)
        5. is_remote flag
        6. "global" fallback
    """
    loc = norm(getattr(job, "location", "") or "")
    tags = job_tags(job)
    geo_hint = norm(getattr(job, "geo_hint", "") or "")

    # --- location string (highest confidence) ---
    if has_any(config.EGYPT_PATTERNS, loc) or has_any(_EGYPT_ARABIC_PATTERNS, loc):
        return "egypt"
    if has_any(KSA_PATTERNS, loc):
        return "ksa"
    if has_any(GULF_OTHER_PATTERNS, loc) or has_any(config.GULF_PATTERNS, loc):
        return "gulf_other"

    # --- tags ---
    if has_any(config.EGYPT_PATTERNS, tags) or has_any(_EGYPT_ARABIC_PATTERNS, tags):
        return "egypt"
    if has_any(KSA_PATTERNS, tags):
        return "ksa"

    # --- connector geo_hint (set by fetch layer) ---
    if geo_hint == "egypt":
        return "egypt"
    if geo_hint == "gulf":
        return "ksa" if has_any(KSA_PATTERNS, tags + " " + loc) else "gulf_other"

    # --- description head ---
    desc_head = job_description(job, limit=400)
    if has_any(config.EGYPT_PATTERNS, desc_head) or has_any(_EGYPT_ARABIC_PATTERNS, desc_head):
        return "egypt"
    if has_any(KSA_PATTERNS, desc_head):
        return "ksa"
    if has_any(GULF_OTHER_PATTERNS, desc_head) or has_any(config.GULF_PATTERNS, desc_head):
        return "gulf_other"

    # --- remote / global fallback ---
    if is_remote_job(job):
        return "remote"
    return "global"


def classify_location(job: Any) -> str:
    """Coarser 3-bucket view: egypt / gulf / global."""
    geo = classify_geo(job)
    if geo == "egypt":
        return "egypt"
    if geo in {"ksa", "gulf_other"}:
        return "gulf"
    return "global"
