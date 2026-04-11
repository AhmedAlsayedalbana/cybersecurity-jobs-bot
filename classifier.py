"""
Job Classification Logic: Blue Team, Red Team, General Cybersecurity.
Location Classification: Egypt, Gulf, Global.
"""

from models import Job, _flatten_tags
import config

BLUE_KEYWORDS = [
    "soc", "security analyst", "incident response",
    "siem", "blue team", "threat detection",
    "defensive security", "forensics", "dfir", "malware analyst",
    "detection engineer", "security monitoring", "splunk", "qradar",
    "security operations", "cyber defense", "security monitor", "blue-team"
]

RED_KEYWORDS = [
    "penetration tester", "pentester", "red team",
    "offensive security", "ethical hacker",
    "bug bounty", "exploit", "vulnerability researcher",
    "oscp", "ceh", "gpen", "penetration testing", "red-team", "offensive-security"
]

def classify_domain(job: Job) -> str:
    """
    Classify a job into 'blue', 'red', or 'general'.
    """
    text = (job.title + " " + job.description + " " + _flatten_tags(job.tags)).lower()

    if any(k in text for k in BLUE_KEYWORDS):
        return "blue"

    if any(k in text for k in RED_KEYWORDS):
        return "red"

    return "general"

def classify_location(job: Job) -> str:
    """
    Classify a job's location into 'egypt', 'gulf', or 'global'.
    """
    loc = job.location.lower()

    if any(x in loc for x in config.EGYPT_PATTERNS):
        return "egypt"

    if any(x in loc for x in config.GULF_PATTERNS):
        return "gulf"

    return "global"
