"""
Job Classification Logic � V19

classify_domain: blue / red / general
classify_location: egypt / gulf / global

V19 FIX � Strict location routing to prevent cross-region leakage:
  - job.location field is AUTHORITATIVE. If it clearly says a region, trust it.
  - Fallback to tags/description ONLY when location field is ambiguous
    (e.g. "Remote", "Worldwide", empty).
  - CRITICAL: If location field already resolved to one region, we NEVER
    override with signals from the other region found in description/tags.
    Example: job.location="Riyadh, Saudi Arabia"  always "gulf",
    even if description mentions "Egyptian candidates welcome".
  - Ambiguity detection: a location is ambiguous if it matches NO pattern
    OR it matches only a generic remote/worldwide signal.
"""

from models import Job, _flatten_tags
from job_intelligence import classify_domain as classify_domain_key
from job_intelligence import classify_location as classify_region

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

# Location field values that are ambiguous (no physical region implied)
_AMBIGUOUS_LOCATION_SIGNALS = {
    "remote", "anywhere", "worldwide", "global", "work from home", "wfh",
    "distributed", "fully remote", "100% remote", "location independent",
    "hybrid", "flexible", "multiple locations", "various",
    "online", "virtual", "unspecified",
}


def _location_is_ambiguous(loc: str) -> bool:
    """
    Returns True if the location string does not clearly identify a physical region.
    We consider a location ambiguous if it's empty, or matches only generic
    remote/flexible signals, i.e. it does NOT contain any Egypt or Gulf geo token.
    """
    if not loc:
        return True
    # If it clearly matches a known region  NOT ambiguous
    if any(x in loc for x in config.EGYPT_PATTERNS):
        return False
    if any(x in loc for x in config.GULF_PATTERNS):
        return False
    # Otherwise (e.g. "Remote", "Worldwide", "Hybrid", unknown city)  ambiguous
    return True


def classify_domain(job: Job) -> str:
    domain = classify_domain_key(job)
    if domain in {"soc", "networksec", "cloudsec", "appsec"}:
        return "blue"
    if domain == "pentest":
        return "red"
    return "general"


def classify_location(job: Job) -> str:
    """
    Classify job location into 'egypt', 'gulf', or 'global'.

    Priority order:
    1. job.location field (AUTHORITATIVE if not ambiguous).
       - Matches Egypt pattern  'egypt'  (no further checks)
       - Matches Gulf pattern   'gulf'   (no further checks)
    2. Only if location is ambiguous (Remote / empty / unknown):
       fall back to tags first, then description � but NEVER mix signals
       from both regions; first match wins.
    3. Default  'global'
    """
    return classify_region(job)
