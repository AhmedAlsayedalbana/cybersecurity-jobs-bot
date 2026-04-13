"""
Job Classification Logic — V15

classify_domain: blue / red / general
classify_location: egypt / gulf / global

V15 fix: location check now falls back to description + tags
if job.location alone is ambiguous (e.g. "Remote", "Worldwide").
"""

from models import Job, _flatten_tags
import config

BLUE_KEYWORDS = [
    "soc", "security analyst", "incident response",
    "siem", "blue team", "threat detection",
    "defensive security", "forensics", "dfir", "malware analyst",
    "detection engineer", "security monitoring", "splunk", "qradar",
    "security operations", "cyber defense", "security monitor", "blue-team",
]

RED_KEYWORDS = [
    "penetration tester", "pentester", "red team",
    "offensive security", "ethical hacker",
    "bug bounty", "exploit", "vulnerability researcher",
    "oscp", "ceh", "gpen", "penetration testing",
    "red-team", "offensive-security",
]


def classify_domain(job: Job) -> str:
    text = (job.title + " " + job.description + " " + _flatten_tags(job.tags)).lower()
    if any(k in text for k in BLUE_KEYWORDS):
        return "blue"
    if any(k in text for k in RED_KEYWORDS):
        return "red"
    return "general"


def classify_location(job: Job) -> str:
    """
    Classify job location into 'egypt', 'gulf', or 'global'.
    Checks: job.location first, then falls back to description + tags
    to catch cases where location = 'Remote' but context is Egypt/Gulf.
    """
    loc = (job.location or "").lower()

    # Primary check — location field
    if any(x in loc for x in config.EGYPT_PATTERNS):
        return "egypt"
    if any(x in loc for x in config.GULF_PATTERNS):
        return "gulf"

    # Fallback — scan description + tags for geo signals
    tags_text = _flatten_tags(job.tags).lower()
    desc_text = (job.description or "").lower()
    extended  = f"{tags_text} {desc_text}"

    if any(x in extended for x in config.EGYPT_PATTERNS):
        return "egypt"
    if any(x in extended for x in config.GULF_PATTERNS):
        return "gulf"

    return "global"
