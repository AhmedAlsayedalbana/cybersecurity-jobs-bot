"""
Job scoring and ranking system — V21

Scoring Philosophy:
- Location is primary signal (Egypt > Gulf > Remote > Global)
- Tech skills capped at +8 to prevent inflation
- Tech score is GATED: only full points for correct-region jobs
- Source quality boost (+2 for verified local sources)
- Freshness matters: bonus for new, penalty for stale
- Hard penalties for non-security / low-quality listings
- SCORE_THRESHOLD = 12 (raised — only meaningful jobs pass)

V21 Changes vs V19:
- SCORE_THRESHOLD logic moved to config.py (now 12, was 8)
- Duplicate detection moved upstream (dedup.py handles URL+title hash)
- Non-cyber titles get -20 (was -15) — effectively always blocked
- Weak security titles get -8 (was -6) — tighter filter
- Global onsite penalty increased: -6 (was -4)
- Clearance penalty increased: -15 (was -12)
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

# Keywords that indicate the job requires local presence in a specific Western country
_CLEARANCE_REQUIRED = [
    "us clearance", "uk sc clearance", "nato clearance", "security clearance required",
    "dv clearance", "strap clearance", "active clearance", "ts/sci", "top secret",
    "must be uk citizen", "must be us citizen", "must hold uk", "must hold us",
    "eligible to work in the uk", "eligible to work in the us",
    "right to work in uk", "right to work in us",
]

# Jobs that look cyber but are not really security-focused
_WEAK_SECURITY_TITLES = [
    "it support", "helpdesk", "help desk", "desktop support",
    "system administrator", "sysadmin", "network administrator",
    "database administrator", "dba", "data entry",
    "sales engineer", "pre-sales", "presales",
    "noc engineer", "noc analyst", "network operations",
    "it manager", "it director", "infrastructure engineer",
    "devops engineer", "site reliability", "sre",
    "data analyst", "business analyst", "project manager",
    "scrum master", "agile coach",
]

# Jobs that appear security-related but are not cybersecurity
_NON_CYBER_SECURITY_TITLES = [
    "physical security", "security guard", "security officer",
    "building security", "event security", "loss prevention",
    "security supervisor", "security manager",  # without cyber/info qualifier
]


def score_job(job: Job) -> int:
    score = 0
    title_text       = job.title.lower()
    description_text = job.description.lower()
    tags_text        = _flatten_tags(job.tags).lower()
    combined         = f"{title_text} {description_text} {tags_text}"

    # ── 0. Hard disqualifiers (check early) ──────────────────
    # Physical security jobs (not cybersecurity)
    if any(k in title_text for k in _NON_CYBER_SECURITY_TITLES):
        has_cyber = any(k in title_text for k in ["cyber", "information", "infosec", "it", "digital"])
        if not has_cyber:
            score -= 20  # Always disqualified

    # Jobs requiring Western security clearance
    if any(k in combined for k in _CLEARANCE_REQUIRED):
        score -= 15

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

    # ── 2. Tech Skills (capped at +8, location-gated) ────────
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

    raw_tech = min(tech_score, 8)

    # Location-gate: global/onsite jobs get reduced tech credit
    # This prevents a high-tech-score global job from outranking
    # a modest local job that's actually relevant to the audience.
    if loc_type == "global" and not job.is_remote and "remote" not in combined:
        score += raw_tech // 2   # 50% tech credit for irrelevant-region jobs
    else:
        score += raw_tech

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
    if any(k in title_text for k in _WEAK_SECURITY_TITLES):
        score -= 8  # was -6

    if "support" in title_text and not any(
        k in title_text for k in ["security", "cyber", "soc", "analyst"]
    ):
        score -= 4

    # Penalize physical/non-cyber security jobs that slipped through
    if any(k in title_text for k in ["guard", "officer"]) and \
       not any(k in title_text for k in ["security engineer", "security analyst",
                                          "cyber", "information security"]):
        score -= 8

    if len(job.title) < 5:
        score -= 8
    if not job.url:
        score -= 10

    if loc_type == "global" and not job.is_remote and "remote" not in combined:
        score -= 6  # was -4

    # Extra penalty for jobs in clearly irrelevant geographies with no remote option
    # (e.g. job in London/New York with no remote mention)
    irrelevant_geo_signals = [
        "london", "new york", "san francisco", "toronto", "sydney",
        "berlin", "paris", "singapore", "amsterdam", "stockholm",
    ]
    if any(sig in (job.location or "").lower() for sig in irrelevant_geo_signals):
        if not job.is_remote and "remote" not in combined:
            score -= 6

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
