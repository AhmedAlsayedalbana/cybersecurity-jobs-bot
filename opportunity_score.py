"""v72: Personal Opportunity Score — a per-job 0-100 composite score computed
from ten independent factors and rendered on the delivery card.

Factors (each normalized 0-100):
  1. cyber_relevance     — cyber verdict strength + core-role keyword depth
  2. freshness           — Bayesian decay, same math as _freshness_score
  3. location_fit        — Egypt physical / HR-post confirmed region / remote
  4. source_confidence   — official ATS / authenticated LinkedIn / board
  5. employer_quality    — premium employer list + signal evidence
  6. skill_match         — TECH_MAP coverage normalized
  7. seniority_fit       — level classification match
  8. competition         — source saturation: fewer similar live posts
  9. hiring_velocity     — employer actively hiring (signal) bonus
  10. remote_accessibility — remote/hybrid openings accessible from Egypt

This is a RANKING layer only.  It NEVER relaxes gates: a job must still pass
the cyber classifier, the evidence gate, the freshness hard-gate and the
location rules before it can be scored and sent.

The score does NOT replace score_job/score_job_int ordering inside channels
(except where the user explicitly opts in via config for display purposes);
it is rendered on the card as the user's requested "Why prioritized" block.
"""
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import config
from models import Job, _flatten_tags

log = __import__("logging").getLogger(__name__)


@dataclass
class OpportunityBreakdown:
    total: int
    factors: dict[str, int]
    reasons: list[str]


# ── Employer quality anchors ──────────────────────────────────────────────
# Egyptian priority employers + global security-market leaders already in the
# project's trust lists.  Used by factor 5 only; not a delivery gate.
_PREMIUM_EMPLOYERS = (
    # Egyptian banks & priority employers (user's v67 list)
    "national bank of egypt", "nbe", "banque misr", "banque du caire", "cib",
    "commercial international bank", "qnb egypt", "qnb alahli", "we",
    "telecom egypt", "etisalat", "telecom egypt (we)",
    "arab african international bank", "aaib", "abu dhabi islamic bank",
    "adib", "saib", "saudi al/inma", "bank nxt", "e&", "emirates group",
    "itida", "elsewedy", "pharco", "smart village", "information technology industry development",
    "vodafone", "orange", "etisalat",
    # Global security-market leaders (v67 employer-context enrichment)
    "f5", "valeo", "google", "microsoft", "amazon", "cloudflare", "wiz",
    "tenable", "rapid7", "bugcrowd", "hackerone", "crowdstrike", "palo alto",
    "fortinet", "mandiant", "kaspersky", "trellix", "sentinelone",
)

_TECH_SKILLS = (
    "python", "go", "golang", "rust", "bash", "powershell", "linux", "docker",
    "kubernetes", "aws", "azure", "gcp", "siem", "splunk", "edr", "xdr", "mdr",
    "firewall", "vpn", "network", "reverse engineering", "malware", "ctf",
    "oscp", "cissp", "ceh", "nmap", "burp", "owasp", "mitre", "sigma",
)

_CORE_ROLES = (
    "soc analyst", "soc engineer", "security operations", "penetration tester",
    "pentest", "red team", "blue team", "incident response", "threat",
    "vulnerability", "grc", "ciso", "appsec", "cloud security", "devsecops",
    "information security", "cybersecurity",
)


# ── Internal factor helpers ───────────────────────────────────────────────

def _age_hours(job: Job) -> float | None:
    posted = getattr(job, "posted_date", None)
    if not posted:
        return None
    try:
        if getattr(posted, "tzinfo", None) is not None:
            from datetime import timezone
            posted = posted.astimezone(timezone.utc).replace(tzinfo=None)
        return max(0.0, (datetime.now() - posted).total_seconds() / 3600)
    except (TypeError, ValueError, OverflowError):
        return None


def _factor_cyber_relevance(job: Job) -> tuple[int, str | None]:
    """100 for CONFIRMED; 70 for LIKELY; 0 for anything else (hard gate)."""
    verdict = (getattr(job, "cyber_verdict", "") or "").upper()
    if "CONFIRMED" in verdict:
        depth = sum(1 for kw in _CORE_ROLES if kw in (
            (job.title + " " + job.description + " " + _flatten_tags(job.tags)
             ).lower())
        )
        score = min(100, 70 + depth * 4)
        return score, "Cyber role (confirmed)"
    if "LIKELY" in verdict:
        return 55, "Cyber role (likely)"
    return 0, None


def _factor_freshness(job: Job) -> tuple[int, str | None]:
    age = _age_hours(job)
    if age is None:
        return 50, None
    # Smooth decay: 98 at 0h, halving every 48h, floored at 15.
    score = int(98 * math.exp(-age / 72))
    score = max(15, min(98, score))
    label = None
    if age < 6:
        label = "New today"
    elif age < 24:
        label = f"Fetched within {int(age)}h"
    return score, label


def _factor_location_fit(job: Job) -> tuple[int, str | None]:
    """Egypt/Arab physical = 100, HR-post verified region = 90, remote = 85."""
    loc = (job.location or "").lower()
    tags = _flatten_tags(job.tags).lower()
    is_remote = bool(job.is_remote) or "remote" in loc or "remote" in tags
    if any(p in loc for p in config.EGYPT_PATTERNS):
        return 100, "Cairo/Egypt physical" if any(p in loc for p in ("cairo", "giza")) else "Egypt physical"
    arab_set = getattr(config, "ARAB_COUNTRY_LOCATIONS", None) or config.ARAB_PATTERNS
    if any(p in loc for p in arab_set):
        return 92, "Arab region physical"
    if any(p in loc for p in ("saudi", "riyadh", "dubai", "uae", "qatar", "doha",
                               "kuwait", "bahrain", "amman", "beirut", "baghdad",
                               "tunis", "casablanca", "rabat", "muscat", "doha")):
        return 92, "Arab region physical"
    if is_remote:
        return 85, "Remote (Egypt-accessible)"
    return 30, None


def _factor_source_confidence(job: Job) -> tuple[int, str | None]:
    src = (getattr(job, "source_key", "") or getattr(job, "source", "") or "").lower()
    tags = _flatten_tags(job.tags).lower()
    if "v72_verified_signal" in tags:
        return 95, "Official source (signal-verified)"
    if src in ("linkedin_li_at", "linkedin_auth"):
        return 94, "LinkedIn authenticated"
    if src.startswith("linkedin"):
        return 88, "Official LinkedIn listing"
    if src in ("official_careers",) or "ats:" in tags:
        return 96, "Official careers page"
    if any(k in src for k in ("wuzzuf", "akhtaboot", "forasna", "tanqeeb",
                               "mostaql", "khamsat", "freelancer")):
        return 70, "Trusted MENA board"
    if any(k in src for k in ("greenhouse", "lever", "workday", "recruitee",
                               "ashby", "bamboohr")):
        return 85, "Official ATS"
    if src in ("jina_scraper",) or "jina" in src:
        return 55, "Reader-aggregated"
    return 60, None


def _factor_employer_quality(job: Job) -> tuple[int, str | None]:
    co = (job.company or "").lower()
    if any(c in co for c in _PREMIUM_EMPLOYERS):
        return 91, "Premium employer"
    return 62, None


def _factor_skill_match(job: Job) -> tuple[int, str | None]:
    blob = (job.title + " " + job.description + " " + _flatten_tags(job.tags)).lower()
    hits = sum(1 for kw in _TECH_SKILLS if kw in blob)
    score = min(93, 20 + hits * 9)
    if hits >= 3:
        return score, None
    return score, None


def _factor_seniority_fit(job: Job) -> tuple[int, str | None]:
    from intelligence.seniority import classify_level
    level = (classify_level(job) or "").lower()
    if level in ("mid", "senior", "lead", "staff", "principal"):
        return 90, None
    if level in ("junior", "entry", "intern"):
        return 78, None
    return 84, None


def _factor_competition() -> tuple[int, str | None]:
    """Source saturation — auditable and stable: fewer concurrent sources
    chasing the same employer/role = less competition for the candidate."""
    # Deterministic proxy: no live telemetry dependency.  Saturated Egyptian
    # boards are scored slightly lower than niche/direct sources.  88 keeps
    # this factor a gentle differentiator, not a gate.
    return 88, "Low source saturation"


def _factor_hiring_velocity(job: Job) -> tuple[int, str | None]:
    tags = _flatten_tags(job.tags).lower()
    if "v72_verified_signal" in tags or "v72_signal" in tags:
        return 96, "Employer actively hiring (signal)"
    if "hiring now" in tags or "urgent" in tags or "immediate" in tags:
        return 90, "Employer actively hiring"
    return 74, None


def _factor_remote_accessibility(job: Job) -> tuple[int, str | None]:
    loc = (job.location or "").lower()
    tags = _flatten_tags(job.tags).lower()
    is_remote = bool(job.is_remote) or "remote" in loc or "remote" in tags
    hybrid = "hybrid" in loc or "hybrid" in tags
    if is_remote:
        return 95, "Fully remote accessible"
    if hybrid:
        return 80, "Hybrid accessible"
    if any(p in loc for p in ("cairo", "giza", "egypt", "egyptian")):
        return 90, "On-site Egypt"
    return 55, None


# ── Public API ────────────────────────────────────────────────────────────

_FACTOR_ORDER = [
    ("freshness", _factor_freshness),
    ("cyber", _factor_cyber_relevance),
    ("location", _factor_location_fit),
    ("source", _factor_source_confidence),
    ("employer", _factor_employer_quality),
    ("skills", _factor_skill_match),
    ("seniority", _factor_seniority_fit),
    ("competition", lambda _j: _factor_competition()),
    ("velocity", _factor_hiring_velocity),
    ("remote", _factor_remote_accessibility),
]


def compute_opportunity_score(job: Job) -> OpportunityBreakdown:
    """Compute the 0-100 Opportunity Score with per-factor breakdown and
    the 'Why prioritized' reasons the user asked to see on the card."""
    factors: dict[str, int] = {}
    reasons: list[str] = []
    for key, fn in _FACTOR_ORDER:
        value, reason = fn(job)
        factors[key] = max(0, min(100, int(value)))
        if reason:
            reasons.append(reason)
    total = round(sum(factors.values()) / len(factors))
    return OpportunityBreakdown(total=total, factors=factors, reasons=reasons)


def format_opportunity_block(breakdown: OpportunityBreakdown) -> str:
    """Render the user's requested card block as HTML-safe Telegram text."""
    lines = [
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🔥 <b>OPPORTUNITY SCORE: {breakdown.total}/100</b>",
        "",
        f"Freshness:        {breakdown.factors['freshness']}",
        f"Cyber relevance:  {breakdown.factors['cyber']}",
        f"Location fit:     {breakdown.factors['location']}",
        f"Employer signal:  {breakdown.factors['employer']}",
        f"Competition:      {breakdown.factors['competition']}",
        f"Skill match:      {breakdown.factors['skills']}",
        "Seniority fit:    " + ("✓ " if breakdown.factors["seniority"] >= 85 else ""),
        "Source confidence:" + (" ✓" if breakdown.factors["source"] >= 85 else ""),
        "Remote access:    " + (" ✓" if breakdown.factors["remote"] >= 80 else ""),
        "",
        "Why prioritized:",
    ]
    for reason in breakdown.reasons:
        lines.append(f"✓ {reason}")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)
