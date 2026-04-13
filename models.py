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

# Expanded CORE_ROLES for better detection
CORE_ROLES = [
    "soc analyst", "soc engineer", "security engineer", "security operations engineer",
    "penetration tester", "pentester", "pentest",
    "appsec", "application security", "cloud security",
    "incident response", "incident responder",
    "threat intelligence", "threat hunter", "threat hunting", "threat analyst",
    "cyber threat intelligence", "cti analyst",
    "dfir", "digital forensics",
    "security architect", "ciso", "grc", "compliance analyst", "security analyst",
    "vulnerability", "ethical hacker", "blue team", "red team", "devsecops",
    "forensics", "malware", "cyber security", "cybersecurity", "infosec",
    "information security", "detection engineer", "security operations",
    "red teamer", "offensive security", "bug bounty", "exploit",
    "iam engineer", "identity access", "pki engineer", "cryptograph",
    "security consultant", "security specialist", "security officer",
    "security administrator", "security manager", "security lead",
]

WEAK_TERMS = ["security", "cyber", "protection", "defense", "analyst"]

def _word_match(keyword: str, text: str) -> bool:
    """
    Match keyword safely:
    - Multi-word phrases: simple substring (already specific enough)
    - Single words: word-boundary match to prevent 'hr' matching inside 'threat'
    """
    import re
    kw = keyword.lower().strip()
    if " " in kw:
        return kw in text
    return bool(re.search(r"\b" + re.escape(kw) + r"\b", text))


def is_cybersec_job(job: "Job") -> bool:
    """
    Return True if job is a Cybersecurity role.
    Uses word-boundary matching on exclude keywords to prevent false positives
    (e.g. 'hr' must not match inside 'threat').
    """
    text = f"{job.title} {job.description} {_flatten_tags(job.tags)}".lower()
    title_lower = job.title.lower()

    # Title-only exclusion — word-boundary aware
    for kw in config.EXCLUDE_KEYWORDS:
        if _word_match(kw, title_lower):
            # Don't exclude if a core security term is also in the title
            if any(role in title_lower for role in ["security", "cyber", "soc", "pentest"]):
                continue
            logger.info(f"Job excluded (Blacklisted keyword in title): {job.title}")
            return False

    # Layer 1: Core Roles (Highest confidence)
    if any(role in text for role in CORE_ROLES):
        return True

    # Layer 2: Weak signals with technical context
    if any(term in text for term in WEAK_TERMS):
        strong_context = [
            "siem", "soc", "edr", "xdr", "pentest", "vulnerability", "firewall",
            "ids/ips", "threat", "splunk", "qradar", "sentinel", "crowdstrike",
            "defender", "wireshark", "metasploit", "burp", "owasp", "iso 27001",
            "nist", "cis", "iam", "pki", "encryption", "hardening"
        ]
        if any(ctx in text for ctx in strong_context):
            return True

        # If it's in Egypt or Gulf, be less strict
        if _is_in_egypt(job.location) or _is_in_gulf(job.location):
            if any(term in title_lower for term in ["security", "cyber"]):
                return True

    logger.info(f"Job excluded (No strong cyber context): {job.title}")
    return False


def passes_geo_filter(job: "Job") -> bool:
    """
    Geo-filtering:
    - Egypt → ALWAYS pass
    - Remote-only sources → auto-pass
    - linkedin_hiring → always pass (location often undetected in canonical titles)
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

    # #Hiring posts: always pass — location extraction is unreliable for these
    if job.source == "linkedin_hiring":
        return True

    if _is_remote(job):
        return True

    if _is_in_gulf(job.location):
        return True

    return False


def filter_jobs(jobs: list["Job"]) -> list["Job"]:
    """
    Apply all filters.
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
