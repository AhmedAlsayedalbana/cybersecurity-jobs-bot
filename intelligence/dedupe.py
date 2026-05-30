"""
intelligence/dedupe.py
======================
Production-grade deduplication helpers.

This module provides the *matching primitives* used by the full dedup
pipeline in dedup.py.  It does NOT touch the database or seen-ID store —
those responsibilities remain in dedup.py for separation of concerns.

Public API:
    normalize_text(text)       → str
    job_fingerprint(job)       → str
    fuzzy_match(fp1, fp2)      → bool
    normalize_url(url)         → str
    are_duplicate_jobs(a, b)   → bool
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

_NOISE_PATTERN = re.compile(
    r"\b(inc|ltd|llc|corp|co|the|a|an|of|for|at|in|and|group|company"
    r"|technologies|services|solutions|systems|global|international)\b"
)
_TRAILING_NUM = re.compile(r"\s*[-–]{1,2}\s*\d{1,3}\s*$")


def normalize_text(text: str) -> str:
    """Lowercase, strip noise words, collapse whitespace."""
    text = text.lower().strip()
    text = _NOISE_PATTERN.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# URL normalization / canonicalization
# ---------------------------------------------------------------------------

_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "ref", "referer", "source", "trk", "trackingId", "li_fat_id",
    "fbclid", "gclid", "msclkid", "yclid",
})


def normalize_url(url: str) -> str:
    """Strip tracking params and normalize URL for dedup comparison."""
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url.strip().lower())
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
        clean_params = {k: v for k, v in params.items() if k not in _TRACKING_PARAMS}
        clean_query = urllib.parse.urlencode(clean_params, doseq=True)
        return urllib.parse.urlunparse((
            parsed.scheme, parsed.netloc, parsed.path.rstrip("/"),
            "", clean_query, "",
        ))
    except Exception:
        return url.strip().lower()


# ---------------------------------------------------------------------------
# Job fingerprint
# ---------------------------------------------------------------------------

def job_fingerprint(job: Any) -> str:
    """Create a canonical fingerprint for fuzzy dedup.

    Format: ``<normalized_title>||<normalized_company>||<normalized_city>``
    """
    title = normalize_text(
        _TRAILING_NUM.sub("", getattr(job, "title", "") or "")
    )
    company = normalize_text(getattr(job, "company", "") or "")
    raw_loc = getattr(job, "location", "") or ""
    city = normalize_text(raw_loc.split(",")[0])
    return f"{title}||{company}||{city}"


# ---------------------------------------------------------------------------
# Fuzzy matching
# ---------------------------------------------------------------------------

def fuzzy_match(fp1: str, fp2: str, threshold: float = 0.72) -> bool:
    """Token-based Jaccard similarity over fingerprint tokens.

    Faster than full string edit distance for our typical fingerprint lengths.
    """
    tokens1 = set(fp1.replace("||", " ").split())
    tokens2 = set(fp2.replace("||", " ").split())
    if not tokens1 or not tokens2:
        return False
    overlap = tokens1 & tokens2
    union = tokens1 | tokens2
    return len(overlap) / len(union) >= threshold


# ---------------------------------------------------------------------------
# Cross-source duplicate detection
# ---------------------------------------------------------------------------

def are_duplicate_jobs(a: Any, b: Any, *, threshold: float = 0.72) -> bool:
    """Return True if two job objects are likely the same posting.

    Checks (in order of cost):
        1. Normalized URL equality (cheapest)
        2. Fingerprint exact match
        3. Fingerprint fuzzy Jaccard similarity
    """
    url_a = normalize_url(getattr(a, "url", "") or "")
    url_b = normalize_url(getattr(b, "url", "") or "")
    if url_a and url_b and url_a == url_b:
        return True

    fp_a = job_fingerprint(a)
    fp_b = job_fingerprint(b)
    if fp_a == fp_b:
        return True

    return fuzzy_match(fp_a, fp_b, threshold=threshold)
