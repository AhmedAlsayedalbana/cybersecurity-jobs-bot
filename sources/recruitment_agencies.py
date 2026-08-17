"""Recruitment agency job fetchers for the MENA region.

Uses the Jina Reader approach (fetch via ``r.jina.ai`` to get markdown,
then parse job listings from the markdown).

Agencies covered:
  1. Michael Page Egypt
  2. Robert Walters MENA
  3. Hays MENA
"""

from __future__ import annotations

import re
import logging
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

_AGENCY_SPECS = [
    {"key": "michaelpage_egypt", "name": "Michael Page Egypt",
     "url": "https://www.michaelpage.com.eg/jobs/cybersecurity", "geo_hint": "egypt"},
    {"key": "robertwalters_mena", "name": "Robert Walters MENA",
     "url": "https://www.robertwalters.com/jobs/cybersecurity", "geo_hint": "gulf"},
    {"key": "hays_mena", "name": "Hays MENA",
     "url": "https://www.hays.com/jobs/cybersecurity", "geo_hint": "gulf"},
]


def _parse_jina_markdown(markdown: str, spec: dict) -> list[dict]:
    """Extract job listings from Jina markdown output."""
    jobs = []
    lines = markdown.split("\n")
    current_job = None
    for line in lines:
        stripped = line.strip()
        if not stripped or len(stripped) < 5:
            continue
        # Skip noise
        if any(skip in stripped.lower() for skip in [
            "sign in", "privacy", "cookies", "terms", "home",
            "about us", "contact", "register", "login", "search",
            "browse", "find jobs", "upload cv", "my account",
        ]):
            current_job = None
            continue
        # Detect job title lines (capitalized, no punctuation at end, reasonable length)
        if current_job and (stripped[0].isupper() or stripped.startswith("\u2022")):
            # Could be company or location info
            if any(loc in stripped.lower() for loc in [
                "egypt", "cairo", "saudi", "riyadh", "uae", "dubai",
                "remote", "qatar", "kuwait", "bahrain", "oman",
                "jordan", "amman", "lebanon", "morocco", "iraq",
            ]):
                current_job["location"] = stripped
            elif len(stripped) < 60 and not stripped.endswith("."):
                current_job["company"] = stripped
        elif 10 < len(stripped) < 80 and not stripped.endswith(".") and stripped[0].isupper():
            if current_job and current_job.get("title"):
                jobs.append(current_job)
            current_job = {
                "title": stripped, "company": "", "location": "",
                "url": spec["url"], "source_key": spec["key"],
            }
    if current_job and current_job.get("title"):
        jobs.append(current_job)
    return jobs


def fetch_recruitment_agencies() -> list[Job]:
    """Fetch cybersecurity jobs from MENA recruitment agency websites."""
    jobs = []
    for spec in _AGENCY_SPECS:
        try:
            jina_url = f"https://r.jina.ai/{spec['url']}"
            markdown = get_text(
                jina_url,
                headers={"Accept": "text/markdown"},
                timeout=15,
                budget_phase="other_sources",
            )
            if not markdown or len(markdown) < 100:
                log.info(" Recruitment agency %s: no content", spec["key"])
                continue
            parsed = _parse_jina_markdown(markdown, spec)
            for j in parsed:
                jobs.append(Job(
                    title=j.get("title", ""),
                    company=j.get("company", "Unknown"),
                    location=j.get("location", ""),
                    url=j.get("url", spec["url"]),
                    source="recruitment_agency",
                    source_key=spec["key"],
                    tags=["recruitment", "agency", spec["geo_hint"]],
                    geo_hint=spec["geo_hint"],
                    origin_priority=50,
                ))
            log.info(" Recruitment agency %s: %d candidates", spec["key"], len(parsed))
        except Exception as exc:
            log.debug(" Recruitment agency %s: error %s", spec["key"], exc)
    return jobs
