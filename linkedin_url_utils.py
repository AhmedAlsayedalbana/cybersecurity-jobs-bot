"""Canonical LinkedIn URL utilities used by scraping, dedup, and messaging."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse


_LINKEDIN_HOSTS = {"linkedin.com", "www.linkedin.com", "m.linkedin.com"}
_LINKEDIN_SOURCE_EXTRAS = {
    "gov_egypt",
    "egypt_alt",
    "egypt_companies",
    "gov_gulf",
    "gulf_expanded",
}


def _clean_host(netloc: str) -> str:
    host = (netloc or "").split("@")[-1].split(":")[0].strip().lower()
    if host == "m.linkedin.com":
        return "www.linkedin.com"
    return host


def is_linkedin_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url.strip())
    host = _clean_host(parsed.netloc)
    return host in _LINKEDIN_HOSTS or host.endswith(".linkedin.com")


def is_linkedin_source(source: str) -> bool:
    s = (source or "").strip().lower()
    return s.startswith("linkedin") or s in _LINKEDIN_SOURCE_EXTRAS


def normalize_linkedin_url(url: str) -> str:
    """Return a canonical LinkedIn URL without tracking params or fragments."""
    if not url:
        return ""
    candidate = unquote(url.strip())
    if candidate.startswith("www.linkedin.com") or candidate.startswith("m.linkedin.com"):
        candidate = "https://" + candidate
    if candidate.startswith("linkedin.com/"):
        candidate = "https://www." + candidate

    parsed = urlparse(candidate)
    host = _clean_host(parsed.netloc)
    if host not in _LINKEDIN_HOSTS and not host.endswith(".linkedin.com"):
        return ""

    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    query = parse_qs(parsed.query or "", keep_blank_values=False)

    current_job_id = ""
    for key in ("currentJobId", "currentjobid"):
        values = query.get(key)
        if values:
            current_job_id = values[0].strip()
            break
    if current_job_id.isdigit():
        return f"https://www.linkedin.com/jobs/view/{current_job_id}/"

    job_match = re.search(r"/jobs/view/(\d{6,})", path)
    if job_match:
        return f"https://www.linkedin.com/jobs/view/{job_match.group(1)}/"

    if path.startswith("/feed/update/"):
        cleaned = path.rstrip("/")
        return f"https://www.linkedin.com{cleaned}"

    if path.startswith("/posts/"):
        cleaned = path.rstrip("/")
        return f"https://www.linkedin.com{cleaned}"

    if "/detail/recent-activity/" in path:
        cleaned = path.rstrip("/")
        return f"https://www.linkedin.com{cleaned}"

    if path.startswith("/jobs/"):
        cleaned = path.rstrip("/")
        return f"https://www.linkedin.com{cleaned}"

    return f"https://www.linkedin.com{path.rstrip('/')}"


def extract_linkedin_job_id(canonical_url: str) -> str:
    if not canonical_url:
        return ""
    match = re.search(r"/jobs/view/(\d{6,})", canonical_url)
    return match.group(1) if match else ""


def extract_linkedin_post_id(canonical_url: str) -> str:
    if not canonical_url:
        return ""

    for pattern in (
        r"urn:li:(?:activity|share):(\d+)",
        r"/posts/[^/?#]*?(\d{8,})(?:-[^/?#]+)?/?$",
        r"/recent-activity/(?:shares|all)/(\d+)/?$",
    ):
        match = re.search(pattern, canonical_url)
        if match:
            return match.group(1)
    return ""


def is_valid_linkedin_canonical(url: str) -> bool:
    canonical = normalize_linkedin_url(url)
    if not canonical:
        return False
    if extract_linkedin_job_id(canonical):
        return True
    if extract_linkedin_post_id(canonical):
        return True
    return False


def canonicalize_job_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if is_linkedin_url(raw):
        return normalize_linkedin_url(raw)
    return raw
