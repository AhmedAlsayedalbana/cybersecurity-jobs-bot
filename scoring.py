"""
Job scoring and ranking system — V32

Built on V31, merges the best ideas from V32-Enterprise:
  ✅ phrase_match()        — flexible regex: handles "cloud-security", "cloud/security", spaces
  ✅ Bayesian freshness    — 6 * exp(-age_hours / 72), smooth decay instead of hard steps
  ✅ diversity_rerank()    — prevents one company/title dominating the feed
  ✅ WEIGHTS dict          — single place to tune all numbers
  ✅ Context weighting     — title ×2, tags ×1.5, description ×1
  ✅ Entry-level gate      — boost only when score >= ENTRY_MIN_SCORE
  ✅ score_job() returns   — (int, list[str]) for full explainability
  ✅ score_job_int()       — backward-compat wrapper for main.py / telegram_sender.py

NOT merged from V32-Enterprise (would break the project):
  ❌ Job dataclass         — project uses models.Job with extra fields
  ❌ classify_location()   — project uses classifier.py with full Arabic patterns
  ❌ Remote double-add     — V32 added +5 AND +2 regardless of location logic
  ❌ seen_duplicates       — belongs in dedup.py, not the scorer
"""

from models import Job, _flatten_tags
from classifier import classify_location
from datetime import datetime
from typing import List, Tuple
import logging
import math
import re

logger = logging.getLogger(__name__)

# =========================================================
# WEIGHTS — single place to tune everything
# =========================================================
WEIGHTS = {
    # Location
    "egypt":         8,
    "gulf":          6,
    "remote":        4,
    "global":        1,
    "hybrid_bonus":  1,

    # Tech
    "tech_cap":      10,
    "tech_global":   0.5,   # multiplier for global-onsite jobs

    # Freshness — Bayesian decay: 6 * exp(-age_h / 72)
    "fresh_peak":    6,
    "fresh_halflife": 72,   # hours at which score halves (≈3 days)
    "fresh_floor":   -4,    # never worse than this

    # Source
    "src_local":     2,
    "src_cybersec":  1,
    "src_direct":    1,
    "src_li_reg":    2,    # v31: raised — LinkedIn is high-quality regional source

    # Company
    "premium_co":    2,

    # Entry-level
    "entry_boost":   3,
    "entry_min":     8,     # gate: only boost if already >= this

    # Penalties
    "non_cyber":    -20,
    "clearance":    -15,
    "weak_title":    -8,
    "support_gen":   -4,
    "guard_title":   -8,
    "short_title":   -8,
    "no_url":       -10,
    "global_onsite": -4,
    "bad_geo":       -4,

    # Diversity rerank
    "div_company":   4,     # penalty per company after 2 appearances
    "div_title":     4,     # penalty per title after 2 appearances
}

# =========================================================
# SOURCE TIERS
# =========================================================
_SOURCE_LOCAL = {
    "wuzzuf", "forasna", "drjobpro", "akhtaboot", "bayt", "naukrigulf",
    "tanqeeb", "arab_boards", "stc_ksa", "tdra_uae", "etisalat_uae",
    "iti", "depi", "nti", "linkedin_egypt_companies", "linkedin_gulf_companies",
}
_SOURCE_CYBERSEC = {
    "bugcrowd", "hackerone", "infosec_jobs", "infosec_jobs.com",
    "cybersecjobs", "clearancejobs", "isaca", "isc2", "cybersec_rss",
}
_SOURCE_DIRECT = {
    "greenhouse_expanded", "greenhouse_cybersec", "lever_expanded",
}
_PREMIUM_COMPANIES = {
    "crowdstrike", "palo alto networks", "sentinelone", "zscaler",
    "cloudflare", "okta", "datadog", "rapid7", "tenable", "qualys",
    "abnormal security", "huntress", "axonius", "wiz", "snyk",
    "recorded future", "darktrace", "vectra ai", "illumio",
    "google", "microsoft", "amazon", "meta", "apple",
}

# =========================================================
# DISQUALIFIER LISTS
# =========================================================
_CLEARANCE_REQUIRED = [
    "us clearance", "uk sc clearance", "nato clearance",
    "security clearance required", "dv clearance", "strap clearance",
    "active clearance", "ts/sci", "top secret",
    "must be uk citizen", "must be us citizen",
    "must hold uk", "must hold us",
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
_NON_CYBER_TITLES = [
    "physical security", "security guard", "security officer",
    "building security", "event security", "loss prevention",
    "security supervisor",
]
_IRRELEVANT_GEO = [
    "london", "new york", "san francisco", "toronto", "sydney",
    "berlin", "paris", "singapore", "amsterdam", "stockholm",
]

# =========================================================
# TECH KEYWORD MAP
# =========================================================
TECH_MAP = {
    # SOC / Blue Team
    "soc analyst": 6,       "soc engineer": 6,      "security operations center": 5,
    "soc": 3,               "blue team": 4,          "threat analyst": 4,
    "siem": 3,              "splunk": 3,              "qradar": 3,         "sentinel": 3,
    "incident response": 4, "threat hunting": 5,     "threat hunter": 5,
    "dfir": 5,              "digital forensics": 4,  "malware analyst": 4,
    "detection engineer": 5,
    # Pentest / Red Team
    "penetration tester": 6, "penetration testing": 6, "pentest": 5,
    "red team": 5,           "offensive security": 4,
    "ethical hacker": 4,     "bug bounty": 4,
    "oscp": 3,               "ceh": 2,                "exploit": 3,
    # Network Security
    "network security engineer": 6, "network security analyst": 6,
    "firewall engineer": 5,         "firewall administrator": 4,
    "intrusion detection": 4,       "intrusion prevention": 4,
    "ids": 3,     "ips": 3,         "zero trust": 3,
    "palo alto": 3, "fortinet": 3,  "cisco security": 3,
    "network defense": 4, "waf engineer": 4, "ddos": 3,
    # Cloud Security
    "cloud security": 5, "aws security": 5, "azure security": 5,
    "kubernetes security": 4, "container security": 3, "cspm": 3,
    # AppSec
    "appsec": 4, "application security": 4, "devsecops": 4,
    "sast": 3,   "dast": 3,                 "owasp": 3,
    # GRC
    "grc": 4,       "iso 27001": 3,     "compliance": 2,
    "nist": 2,      "risk analyst": 3,  "security auditor": 3,
    # General
    "vulnerability": 2, "ciso": 2, "security architect": 4, "cryptograph": 2,
}

_ENTRY_KW = [
    "junior", "intern", "internship", "trainee",
    "fresh grad", "fresh graduate", "entry level", "entry-level",
    "graduate program", "0-1 years", "0-2 years", "1-2 years",
]


# =========================================================
# HELPERS
# =========================================================

def phrase_match(phrase: str, text: str) -> bool:
    """
    Flexible word-boundary match from V32-Enterprise.
    Handles: 'cloud security', 'cloud-security', 'cloud/security'.
    Prevents false positives like 'ids' matching inside 'considers'.
    """
    try:
        escaped = re.escape(phrase).replace(r"\ ", r"[\s\-_/]*")
        return bool(re.search(rf"\b{escaped}\b", text))
    except Exception:
        return phrase in text


def _freshness_score(posted_date) -> Tuple[int, str]:
    """
    Bayesian decay from V32-Enterprise: score = 6 * exp(-age_hours / 72).
    Smooth curve instead of hard steps — job 3h old gets ~5.9, 72h gets ~2.2, 7d gets ~0.
    Floor at WEIGHTS['fresh_floor'] so very old jobs still get penalised but not infinitely.
    """
    if not posted_date:
        return 0, ""
    age_h = (datetime.now() - posted_date).total_seconds() / 3600
    raw   = WEIGHTS["fresh_peak"] * math.exp(-age_h / WEIGHTS["fresh_halflife"])
    score = max(WEIGHTS["fresh_floor"], round(raw))
    if score > 0:
        return score, f"+{score} fresh"
    elif score < 0:
        return score, f"{score} stale"
    return 0, ""


# =========================================================
# MAIN SCORER
# =========================================================

def score_job(job: Job) -> Tuple[int, List[str]]:
    """
    Score a job. Returns (score: int, reasons: list[str]).

    Usage:
        score, reasons = score_job(job)
        # or for just the number:
        score = score_job_int(job)
    """
    score   = 0
    reasons = []

    title = (job.title or "").lower()
    desc  = (job.description or "").lower()
    tags  = _flatten_tags(job.tags).lower()

    # ── 0. Hard disqualifiers ────────────────────────────────
    if any(phrase_match(k, title) for k in _NON_CYBER_TITLES):
        has_cyber = any(phrase_match(k, title) for k in
                        ["cyber", "information", "infosec", "it", "digital"])
        if not has_cyber:
            score += WEIGHTS["non_cyber"]
            reasons.append(f"{WEIGHTS['non_cyber']} non-cyber title")

    quick_scan = title + " " + desc[:200] + " " + tags
    if any(k in quick_scan for k in _CLEARANCE_REQUIRED):
        score += WEIGHTS["clearance"]
        reasons.append(f"{WEIGHTS['clearance']} clearance required")

    # ── 1. Location ──────────────────────────────────────────
    try:
        loc_type = classify_location(job)
    except Exception:
        loc_lower = (job.location or "").lower()
        if "egypt" in loc_lower or "cairo" in loc_lower:
            loc_type = "egypt"
        elif any(x in loc_lower for x in ["saudi", "uae", "dubai", "qatar", "kuwait"]):
            loc_type = "gulf"
        else:
            loc_type = "global"

    is_remote = job.is_remote or phrase_match("remote", title + " " + desc[:80] + " " + tags)

    if loc_type == "egypt":
        score += WEIGHTS["egypt"]
        reasons.append(f"+{WEIGHTS['egypt']} Egypt")
    elif loc_type == "gulf":
        score += WEIGHTS["gulf"]
        reasons.append(f"+{WEIGHTS['gulf']} Gulf")
    elif is_remote:
        score += WEIGHTS["remote"]
        reasons.append(f"+{WEIGHTS['remote']} remote")
    else:
        score += WEIGHTS["global"]
        reasons.append(f"+{WEIGHTS['global']} global onsite")

    # Hybrid only when Egypt/Gulf + confirmed remote option
    if loc_type in ("egypt", "gulf") and is_remote:
        score += WEIGHTS["hybrid_bonus"]
        reasons.append(f"+{WEIGHTS['hybrid_bonus']} hybrid")

    # ── 2. Tech skills — context-weighted ────────────────────
    tech_cap   = WEIGHTS["tech_cap"]
    tech_score = 0.0
    matched    = []

    for kw, val in TECH_MAP.items():
        if tech_score >= tech_cap:
            break
        if phrase_match(kw, title):       # title — highest signal
            tech_score += val * 2
            matched.append(kw)
        elif phrase_match(kw, tags):      # tags — medium signal
            tech_score += val * 1.5
            matched.append(kw)
        elif phrase_match(kw, desc):      # description — base signal
            tech_score += val

    raw_tech = min(int(tech_score), tech_cap)

    if loc_type == "global" and not is_remote:
        credit = int(raw_tech * WEIGHTS["tech_global"])
        score += credit
        if raw_tech:
            reasons.append(f"+{credit} tech (global penalty, raw={raw_tech})")
    else:
        score += raw_tech
        if raw_tech:
            top = ", ".join(matched[:3])
            reasons.append(f"+{raw_tech} tech ({top})" if top else f"+{raw_tech} tech")

    # ── 3. Freshness — Bayesian decay ────────────────────────
    fresh_pts, fresh_label = _freshness_score(job.posted_date)
    score += fresh_pts
    if fresh_label:
        reasons.append(fresh_label)

    # ── 4. Source quality ────────────────────────────────────
    src = (job.source or "").lower()
    if src in _SOURCE_LOCAL:
        score += WEIGHTS["src_local"]
        reasons.append(f"+{WEIGHTS['src_local']} local source")
    elif src in _SOURCE_CYBERSEC:
        score += WEIGHTS["src_cybersec"]
        reasons.append(f"+{WEIGHTS['src_cybersec']} cybersec board")
    elif src in _SOURCE_DIRECT:
        score += WEIGHTS["src_direct"]
        reasons.append(f"+{WEIGHTS['src_direct']} direct page")
    elif src in ("linkedin", "linkedin_hiring", "linkedin_posts", "linkedin_hr"):
        score += WEIGHTS["src_li_reg"]
        reasons.append(f"+{WEIGHTS['src_li_reg']} linkedin source")

    company_lower = (job.company or "").lower()
    if any(c in company_lower for c in _PREMIUM_COMPANIES):
        score += WEIGHTS["premium_co"]
        reasons.append(f"+{WEIGHTS['premium_co']} premium company")

    # ── 5. Entry-level CONDITIONAL ───────────────────────────
    if any(phrase_match(k, title + " " + desc[:200]) for k in _ENTRY_KW):
        if score >= WEIGHTS["entry_min"]:
            score += WEIGHTS["entry_boost"]
            reasons.append(f"+{WEIGHTS['entry_boost']} entry-level")
        else:
            reasons.append("0 entry skipped (score too low)")

    # ── 6. Penalties ─────────────────────────────────────────
    if any(phrase_match(k, title) for k in _WEAK_SECURITY_TITLES):
        score += WEIGHTS["weak_title"]
        reasons.append(f"{WEIGHTS['weak_title']} weak title")

    if "support" in title and not any(
        phrase_match(k, title) for k in ["security", "cyber", "soc", "analyst"]
    ):
        score += WEIGHTS["support_gen"]
        reasons.append(f"{WEIGHTS['support_gen']} generic support")

    if any(phrase_match(k, title) for k in ["guard", "officer"]) and \
       not any(phrase_match(k, title) for k in
               ["security engineer", "security analyst", "cyber", "information security"]):
        score += WEIGHTS["guard_title"]
        reasons.append(f"{WEIGHTS['guard_title']} guard/officer title")

    if len(job.title) < 5:
        score += WEIGHTS["short_title"]
        reasons.append(f"{WEIGHTS['short_title']} title too short")

    if not job.url:
        score += WEIGHTS["no_url"]
        reasons.append(f"{WEIGHTS['no_url']} no URL")

    if loc_type == "global" and not is_remote:
        score += WEIGHTS["global_onsite"]
        reasons.append(f"{WEIGHTS['global_onsite']} global onsite")

    if any(sig in (job.location or "").lower() for sig in _IRRELEVANT_GEO):
        if not is_remote:
            score += WEIGHTS["bad_geo"]
            reasons.append(f"{WEIGHTS['bad_geo']} bad geo")

    return score, reasons


# =========================================================
# BACKWARD-COMPAT WRAPPER
# =========================================================

def score_job_int(job: Job) -> int:
    """Drop-in replacement for the old score_job() → int."""
    s, _ = score_job(job)
    return s


# =========================================================
# DIVERSITY RERANK  (from V32-Enterprise)
# =========================================================

def diversity_rerank(
    rows: List[Tuple],
    max_per_company: int = 2,
    max_per_title: int   = 2,
) -> List[Tuple]:
    """
    Prevents one company or one role from flooding the feed.
    Applies a soft penalty (not hard filter) so legitimate
    top-scoring duplicates don't vanish — they just rank lower.

    Input:  [(job, score, reasons), ...]  — already sorted descending
    Output: re-sorted list after diversity penalty
    """
    company_count: dict = {}
    title_count:   dict = {}
    result         = []

    for item in rows:
        job   = item[0]
        score = item[1]
        extra = item[2:]   # handles (job, score) or (job, score, reasons)

        c = (job.company or "unknown").lower().strip()
        t = (job.title   or "").lower().strip()

        penalty = 0
        if company_count.get(c, 0) >= max_per_company:
            penalty += WEIGHTS["div_company"]
        if title_count.get(t, 0) >= max_per_title:
            penalty += WEIGHTS["div_title"]

        company_count[c] = company_count.get(c, 0) + 1
        title_count[t]   = title_count.get(t,   0) + 1

        result.append((job, score - penalty) + extra)

    result.sort(key=lambda x: -x[1])
    return result


# =========================================================
# LOCATION PRIORITY SORT  (used by main.py)
# =========================================================

def sort_by_location_priority(jobs_with_scores: list) -> list:
    """Sort (job, score) pairs: Egypt → Gulf → Rest, then by score within each."""
    def priority(item):
        job, score = item[0], item[1]
        try:
            loc = classify_location(job)
        except Exception:
            loc = "global"
        return (0 if loc == "egypt" else 1 if loc == "gulf" else 2, -score)
    return sorted(jobs_with_scores, key=priority)
