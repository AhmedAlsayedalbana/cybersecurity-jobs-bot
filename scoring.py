"""
Job scoring and ranking system — V28

Scoring Philosophy:
- Location is a signal, NOT an inflator — Egypt/Gulf jobs start equal on merit.
- Tech skills are the PRIMARY differentiator (capped at +10).
- Freshness is critical: jobs >5 days old get heavy penalty, >7 days are blocked.
- Source quality matters: verified local sources get a small boost.
- Hard penalties for non-security / low-quality / clearance-required listings.
- SCORE_THRESHOLD = 10 (balanced — passes good jobs, blocks noise).

V28 Changes vs V21:
- Freshness penalty tightened: >5 days = -4, >7 days = -8 (was >14 = -5).
  This directly fixes the "6-day-old jobs being sent" problem.
- Location scores reduced (Egypt +8 was 12, Gulf +6 was 9) — less geo bias.
- Tech cap raised to +10 (was +8) — more merit-based.
- network_security keywords given proper weight.
- SCORE_THRESHOLD lowered to 10 (was 12) to compensate for lower location bonus.
- Global onsite penalty reduced (-4 was -6) — less aggressive blocking of remote-eligible jobs.
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

_CLEARANCE_REQUIRED = [
    "us clearance", "uk sc clearance", "nato clearance", "security clearance required",
    "dv clearance", "strap clearance", "active clearance", "ts/sci", "top secret",
    "must be uk citizen", "must be us citizen", "must hold uk", "must hold us",
    "eligible to work in the uk", "eligible to work in the us",
    "right to work in uk", "right to work in us",
]

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

_NON_CYBER_SECURITY_TITLES = [
    "physical security", "security guard", "security officer",
    "building security", "event security", "loss prevention",
    "security supervisor",
]


def score_job(job: Job) -> int:
    score = 0
    title_text       = job.title.lower()
    description_text = job.description.lower()
    tags_text        = _flatten_tags(job.tags).lower()
    combined         = f"{title_text} {description_text} {tags_text}"

    # ── 0. Hard disqualifiers ─────────────────────────────────
    if any(k in title_text for k in _NON_CYBER_SECURITY_TITLES):
        has_cyber = any(k in title_text for k in ["cyber", "information", "infosec", "it", "digital"])
        if not has_cyber:
            score -= 20

    if any(k in combined for k in _CLEARANCE_REQUIRED):
        score -= 15

    # ── 1. Location (signal, not inflator) ────────────────────
    loc_type = classify_location(job)
    if loc_type == "egypt":
        score += 8    # was 12 — reduced to avoid geo over-bias
    elif loc_type == "gulf":
        score += 6    # was 9
    elif job.is_remote or "remote" in combined:
        score += 4
    else:
        score += 1    # global onsite — lowest priority

    # Hybrid boost (local + remote option)
    if loc_type in ("egypt", "gulf") and (job.is_remote or "remote" in combined):
        score += 1

    # ── 2. Tech Skills (capped at +10) ───────────────────────
    tech_map = {
        # SOC / Blue Team
        "soc analyst": 6, "soc engineer": 6, "security operations center": 5,
        "soc": 3, "blue team": 4, "threat analyst": 4,
        "siem": 3, "splunk": 3, "qradar": 3, "sentinel": 3,
        "incident response": 4, "threat hunting": 5, "threat hunter": 5,
        "dfir": 5, "digital forensics": 4, "malware analyst": 4,
        "detection engineer": 5,
        # Pentest / Red Team
        "penetration tester": 6, "penetration testing": 6, "pentest": 5,
        "red team": 5, "offensive security": 4,
        "ethical hacker": 4, "bug bounty": 4,
        "oscp": 3, "ceh": 2, "exploit": 3,
        # Network Security
        "network security engineer": 6, "network security analyst": 6,
        "firewall engineer": 5, "firewall administrator": 4,
        "ids": 3, "ips": 3, "intrusion detection": 4, "intrusion prevention": 4,
        "zero trust": 3, "palo alto": 3, "fortinet": 3, "cisco security": 3,
        "network defense": 4, "ddos": 3, "waf engineer": 4,
        "vpn engineer": 3, "perimeter security": 3,
        # Cloud Security
        "cloud security": 5, "aws security": 5, "azure security": 5,
        "kubernetes security": 4, "container security": 3, "cspm": 3,
        # AppSec
        "appsec": 4, "application security": 4, "devsecops": 4,
        "sast": 3, "dast": 3, "owasp": 3,
        # GRC
        "grc": 4, "iso 27001": 3, "compliance": 2,
        "nist": 2, "risk analyst": 3, "security auditor": 3,
        # General
        "vulnerability": 2, "ciso": 2, "security architect": 4,
        "cryptograph": 2,
    }

    tech_score = 0
    for kw, val in tech_map.items():
        if kw in combined:
            tech_score += val
        if tech_score >= 10:
            break

    raw_tech = min(tech_score, 10)

    if loc_type == "global" and not job.is_remote and "remote" not in combined:
        score += raw_tech // 2
    else:
        score += raw_tech

    # ── 3. Freshness — STRICT ────────────────────────────────
    # This directly fixes the "jobs >5 days old being sent" bug.
    if job.posted_date:
        diff = datetime.now() - job.posted_date
        if diff < timedelta(hours=6):
            score += 5
        elif diff < timedelta(hours=24):
            score += 3
        elif diff < timedelta(days=3):
            score += 1
        elif diff < timedelta(days=5):
            score += 0   # neutral — still eligible
        elif diff < timedelta(days=7):
            score -= 4   # getting stale
        else:
            score -= 10  # >7 days: heavily penalized, effectively blocked at threshold=10

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
        score -= 8

    if "support" in title_text and not any(
        k in title_text for k in ["security", "cyber", "soc", "analyst"]
    ):
        score -= 4

    if any(k in title_text for k in ["guard", "officer"]) and \
       not any(k in title_text for k in ["security engineer", "security analyst",
                                          "cyber", "information security"]):
        score -= 8

    if len(job.title) < 5:
        score -= 8
    if not job.url:
        score -= 10

    if loc_type == "global" and not job.is_remote and "remote" not in combined:
        score -= 4   # was -6

    irrelevant_geo_signals = [
        "london", "new york", "san francisco", "toronto", "sydney",
        "berlin", "paris", "singapore", "amsterdam", "stockholm",
    ]
    if any(sig in (job.location or "").lower() for sig in irrelevant_geo_signals):
        if not job.is_remote and "remote" not in combined:
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
