"""
Job data model and filtering logic.
Cybersecurity-only filtering with smart geo rules:
  - Egypt: all jobs (onsite + remote) — HIGHEST PRIORITY
  - Remote: pass
  - Gulf (KSA/UAE/etc): pass
  - Rest of world: remote only
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
import config
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def _flatten_tags(tags) -> str:
    """Safely flatten tags to a string."""
    if not tags:
        return ""
    flat = []
    for item in tags:
        if isinstance(item, list):
            flat.extend(str(i) for i in item)
        elif isinstance(item, dict):
            flat.append(str(item.get("name", item.get("label", ""))))
        else:
            flat.append(str(item))
    return " ".join(flat)


@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    source: str
    salary: str = ""
    job_type: str = ""
    tags: list = field(default_factory=list)
    is_remote: bool = False
    original_source: str = ""  # for aggregators like JSearch
    posted_date: Optional[datetime] = None
    description: str = ""

    @property
    def unique_id(self) -> str:
        """Dedup key: normalized title + company."""
        title_norm = self.title.lower().strip()
        company_norm = self.company.lower().strip()
        for noise in ["inc", "inc.", "ltd", "ltd.", "llc", "corp",
                      "corporation", "co.", "company", "gmbh", "ag",
                      "sa", "pvt"]:
            company_norm = company_norm.replace(noise, "").strip()
        return f"{title_norm}|{company_norm}"

    @property
    def url_id(self) -> str:
        """Secondary dedup key based on URL."""
        if self.url:
            clean = self.url.split("?utm")[0].split("&utm")[0]
            clean = clean.rstrip("/").lower()
            return clean
        return ""

    @property
    def display_source(self) -> str:
        if self.original_source:
            return self.original_source
        return config.SOURCE_DISPLAY.get(self.source, self.source.title())

    @property
    def emoji(self) -> str:
        text = f"{self.title} {self.location} {_flatten_tags(self.tags)}".lower()
        for keyword, em in config.EMOJI_MAP.items():
            if keyword in text:
                return em
        return config.DEFAULT_EMOJI


# ─── Geo helpers ─────────────────────────────────────────────

def _is_in_egypt(location: str) -> bool:
    loc = location.lower().strip()
    return any(p in loc for p in config.EGYPT_PATTERNS)


def _is_in_gulf(location: str) -> bool:
    loc = location.lower().strip()
    return any(p in loc for p in config.GULF_PATTERNS)


def _is_remote(job: "Job") -> bool:
    if job.is_remote:
        return True
    combined = f"{job.title} {job.location} {job.job_type} {_flatten_tags(job.tags)}".lower()
    return any(p in combined for p in config.REMOTE_PATTERNS)


# ─── Keyword helpers ─────────────────────────────────────────

CORE_ROLES = [
    "soc analyst", "security engineer", "penetration tester", "pentester",
    "appsec", "cloud security", "incident response", "threat intelligence",
    "security architect", "ciso", "grc", "compliance analyst", "security analyst"
]

WEAK_TERMS = ["security", "cyber"]

def is_cybersec_job(job: "Job") -> bool:
    """
    Return True only if job is clearly a Cybersecurity role.
    Layered Filtering:
      Layer 1: Must-have roles (CORE_ROLES)
      Layer 2: Weak signals (WEAK_TERMS) + Strong technical context (SIEM, SOC, etc.)
    """
    text = f"{job.title} {job.description} {_flatten_tags(job.tags)}".lower()
    title_lower = job.title.lower()

    # Title-only exclusion check (prevent false positives on HR/sales roles)
    if any(kw.lower() in title_lower for kw in config.EXCLUDE_KEYWORDS):
        logger.info(f"Job excluded (Blacklisted keyword in title): {job.title}")
        return False

    # Layer 1: Core Roles
    if any(role in text for role in CORE_ROLES):
        return True

    # Layer 2: Weak signals with additional context
    if any(term in text for term in WEAK_TERMS):
        strong_context = ["siem", "soc", "edr", "xdr", "pentest", "vulnerability", "firewall", "ids/ips", "threat"]
        if any(ctx in text for ctx in strong_context):
            return True
        logger.info(f"Job excluded (Weak signal without context): {job.title}")
        return False

    logger.info(f"Job excluded (No cyber keywords): {job.title}")
    return False


def passes_geo_filter(job: "Job") -> bool:
    """
    Geo-filtering:
    - Egypt → ALWAYS pass (top priority)
    - Remote-only sources → auto-pass
    - Remote job → pass
    - Gulf → pass
    - Onsite outside Egypt/Gulf → reject
    """
    remote_only_sources = {
        "remotive", "remoteok", "wwr", "workingnomads", "findwork", "reed",
        "himalayas", "jobicy", "arbeitnow",
    }

    if _is_in_egypt(job.location):
        return True

    if job.source in remote_only_sources:
        return True

    if _is_remote(job):
        return True

    if _is_in_gulf(job.location):
        return True

    return False


def filter_jobs(jobs: list["Job"]) -> list["Job"]:
    """
    Apply all filters:
    1. Must have title and URL
    2. Must be a cybersecurity job
    3. Must pass geo filter
    """
    filtered = []
    for job in jobs:
        if not job.title or not job.url:
            continue
        if not is_cybersec_job(job):
            continue
        if not passes_geo_filter(job):
            continue
        filtered.append(job)
    
    logger.info(f"Filtered {len(jobs)} jobs down to {len(filtered)}")
    return filtered
