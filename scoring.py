"""
Job scoring and ranking system — V15

Scoring Philosophy:
- Location is primary signal (Egypt > Gulf > Remote > Global)
- Tech skills capped at +8 to prevent inflation
- Source quality boost (+2 for verified local sources)
- Freshness matters: bonus for new, penalty for stale
- Hard penalties for non-security / low-quality listings
- SCORE_THRESHOLD = 12 (meaningful filter now)
"""

from models import Job, _flatten_tags
from classifier import classify_location
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# ── Source quality tiers ──────────────────────────────────────
_SOURCE_LOCAL = {
    "wuzzuf", "forasna", "drjobpro", "akhtaboot", "bayt", "naukrigulf",
    "stc_ksa", "tdra_uae", "etisalat_uae", "iti", "depi", "nti",
    "linkedin_egypt_companies", "linkedin_gulf_companies",
}
_SOURCE_CYBERSEC = {
    "bugcrowd", "hackerone", "infosec_jobs", "cybersecjobs", "clearancejobs",
    "isaca", "isc2",
}


def score_job(job: Job) -> int:
    score = 0
    title_text       = job.title.lower()
    description_text = job.description.lower()
    tags_text        = _flatten_tags(job.tags).lower()
    combined         = f"{title_text} {description_text} {tags_text}"

    # ── 1. Location (primary signal) ─────────────────────────
    loc_type = classify_location(job)
    if loc_type == "egypt":
        score += 12
    elif loc_type == "gulf":
        score += 9
    elif job.is_remote or "remote" in combined:
        score += 5
    else:
        score += 2  # global onsite — lowest priority

    # Hybrid boost (Egypt/Gulf + remote option)
    if loc_type in ("egypt", "gulf") and (job.is_remote or "remote" in combined):
        score += 2

    # ── 2. Tech Skills (capped at +8) ────────────────────────
    tech_map = {
        "soc analyst": 5, "soc engineer": 5, "security operations center": 5,
        "soc": 3, "blue team": 4, "threat analyst": 4,
        "siem": 3, "splunk": 3, "qradar": 3, "sentinel": 3,
        "incident response": 4, "threat hunting": 4,
        "dfir": 4, "digital forensics": 4, "malware analyst": 4,
        "detection engineer": 4,
        "penetration tester": 5, "penetration testing": 5, "pentest": 5,
        "red team": 5, "offensive security": 4,
        "ethical hacker": 4, "bug bounty": 4,
        "oscp": 3, "ceh": 2, "exploit": 3,
        "network security": 5, "firewall": 3,
        "ids": 2, "ips": 2, "zero trust": 3,
        "palo alto": 3, "fortinet": 3, "cisco security": 3,
        "cloud security": 4, "aws security": 4, "azure security": 4,
        "appsec": 3, "application security": 3, "devsecops": 3,
        "sast": 2, "dast": 2,
        "grc": 3, "iso 27001": 3, "compliance": 2,
        "nist": 2, "risk analyst": 3, "security auditor": 3,
        "vulnerability": 2, "ciso": 2, "security architect": 3,
        "cryptograph": 2,
    }

    tech_score = 0
    for kw, val in tech_map.items():
        if kw in combined:
            tech_score += val
        if tech_score >= 8:
            break

    score += min(tech_score, 8)

    # ── 3. Freshness ──────────────────────────────────────────
    if job.posted_date:
        diff = datetime.now() - job.posted_date
        if diff < timedelta(hours=6):
            score += 5
        elif diff < timedelta(hours=24):
            score += 3
        elif diff < timedelta(days=3):
            score += 1
        elif diff > timedelta(days=14):
            score -= 5
        elif diff > timedelta(days=7):
            score -= 2

    # ── 4. Source quality boost ───────────────────────────────
    src = (job.source or "").lower()
    if src in _SOURCE_LOCAL:
        score += 2
    elif src in _SOURCE_CYBERSEC:
        score += 1
    elif src == "linkedin":
        if any(t in tags_text for t in ["egypt", "gulf", "saudi", "uae"]):
            score += 1

    # ── 5. Entry-level support ────────────────────────────────
    entry_kw = [
        "junior", "intern", "internship", "trainee",
        "fresh grad", "fresh graduate", "entry level", "entry-level",
        "graduate program", "0-1 years", "0-2 years", "1-2 years",
    ]
    if any(k in combined for k in entry_kw):
        score += 3

    # ── 6. Penalties ─────────────────────────────────────────
    non_sec_titles = [
        "it support", "helpdesk", "help desk", "desktop support",
        "system administrator", "sysadmin", "network administrator",
        "database administrator", "dba", "data entry",
        "sales engineer", "pre-sales", "presales",
    ]
    if any(k in title_text for k in non_sec_titles):
        score -= 6

    if "support" in title_text and not any(
        k in title_text for k in ["security", "cyber", "soc", "analyst"]
    ):
        score -= 4

    if len(job.title) < 5:
        score -= 8
    if not job.url:
        score -= 10

    if loc_type == "global" and not job.is_remote and "remote" not in combined:
        score -= 4

    return score


def sort_by_location_priority(jobs_with_scores: list[tuple[Job, int]]) -> list[tuple[Job, int]]:
    def loc_priority(item):
        job, score = item
        loc = classify_location(job)
        if loc == "egypt":
            return (0, -score)
        if loc == "gulf":
            return (1, -score)
        return (2, -score)

    return sorted(jobs_with_scores, key=loc_priority)
