"""
intelligence/intent.py
======================
Cyber-intent classification — the primary accept/reject gate.

Public API:
    CyberIntentDecision        dataclass
    classify_cyber_intent(job) → CyberIntentDecision
    hard_reject_reason(job)    → str | None
    has_strong_cyber_anchor(job) → bool
    is_true_security_internship(job) → bool
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from intelligence._text import (
    count_hits,
    has_any,
    job_description,
    job_full_text,
    job_tags,
    job_title,
)
from intelligence.patterns import (
    BUSINESS_RISK_REJECTS,
    COMMERCIAL_HARD_REJECTS,
    CYBER_CONTEXT_PATTERNS,
    CYBER_RISK_OVERRIDE_PATTERNS,
    CYBER_TITLE_OVERRIDE_PATTERNS,
    DOMAIN_PATTERNS,
    ENTRY_RE,
    GENERIC_TECH_REJECTS,
    PHYSICAL_HARD_REJECTS,
    SECURITY_TITLE_PREFIXES,
    STRONG_TITLE_PATTERNS,
)


@dataclass(slots=True)
class CyberIntentDecision:
    accept: bool
    reason_code: str
    confidence: float
    reasons: list[str]
    borderline: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _has_cyber_override(job: Any) -> bool:
    """Return True when the job context is strongly cyber despite a generic title."""
    title = job_title(job)
    full = job_full_text(job)
    if has_any(CYBER_RISK_OVERRIDE_PATTERNS, full):
        return True
    if has_any(CYBER_TITLE_OVERRIDE_PATTERNS, title):
        return True
    return count_hits(CYBER_CONTEXT_PATTERNS, full) >= 3


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def hard_reject_reason(job: Any) -> str | None:
    """Return a reject code if the job is a known non-cyber false positive."""
    title = job_title(job)
    full = job_full_text(job, desc_limit=350)

    if has_any(PHYSICAL_HARD_REJECTS, title) and not _has_cyber_override(job):
        return "reject_physical_or_facility_security"

    if has_any(COMMERCIAL_HARD_REJECTS, title):
        return "reject_commercial_cyber_adjacent"

    if has_any(BUSINESS_RISK_REJECTS, title) and not _has_cyber_override(job):
        return "reject_business_or_credit_risk"

    # ✅ v47: Security-prefixed technical titles bypass the generic-tech reject.
    # e.g. "Security Software Engineer", "Security Program Manager" are cyber roles.
    # Check the FULL title string for override patterns first, THEN apply prefix bypass.
    if has_any(GENERIC_TECH_REJECTS, title) and not _has_cyber_override(job):
        title_lower = (title or "").lower()
        if not any(title_lower.startswith(prefix) for prefix in SECURITY_TITLE_PREFIXES):
            return "reject_generic_tech_title"

    if has_any(["application support", "technical support", "help desk", "helpdesk"], title):
        if not has_any(["soc", "siem", "incident response", "security operations", "edr", "xdr"], full):
            return "reject_generic_support_role"

    # A generic executive title becomes a false positive when an unrelated job
    # description merely mentions security.  Keep genuine CISO/security-lead
    # roles, but require a specific cyber title anchor for broad leadership.
    if has_any(["general manager", "country manager", "chief technology officer", "cto"], title):
        if not has_any(["cybersecurity", "cyber security", "information security", "infosec", "ciso"], title):
            return "reject_generic_leadership_title"

    if has_any(["solutions architect", "solution architect"], title):
        if not _has_cyber_override(job):
            return "reject_generic_solutions_architect"

    # ✅ v46: reject "security" titles that are clearly non-cyber
    # e.g. "Food Security Analyst", "Security of Supply", "Supply Security"
    if has_any(["food security", "supply security", "energy security", "water security",
                "national security analyst", "border security", "port security",
                "transportation security", "cargo security"], title):
        if not _has_cyber_override(job):
            return "reject_non_cyber_security_domain"

    # ✅ v46: reject generic IT admin roles unless cyber context is clear
    if has_any(["it manager", "it director", "it coordinator", "it administrator",
                "it support", "it helpdesk"], title):
        if count_hits(CYBER_CONTEXT_PATTERNS, full) < 2:
            return "reject_generic_it_management"

    return None


def has_strong_cyber_anchor(job: Any) -> bool:
    title = job_title(job)
    full = job_full_text(job)
    return (
        count_hits(STRONG_TITLE_PATTERNS, title) >= 1
        or count_hits(CYBER_CONTEXT_PATTERNS, full) >= 2
    )


def is_true_security_internship(job: Any) -> bool:
    """
    Returns True when a job is a genuine cybersecurity internship or entry-level role.

    Detection tiers (strictest first):
      1. Title contains a security-specific intern/trainee compound keyword →
         needs ≥1 cyber context hit in full text.
      2. Title contains generic intern/trainee/graduate/entry-level word →
         needs ≥2 cyber context hits in full text.
      3. Title contains 'junior' + a security term → needs ≥2 cyber context hits.
      4. ENTRY_RE found in full text + title has a broad security word →
         needs ≥3 cyber context hits (conservative).
    """
    title = job_title(job)
    full = job_full_text(job)

    # Tier 1 — security-specific intern compound (e.g. "Cybersecurity Intern")
    if has_any(DOMAIN_PATTERNS["internships"], title):
        if has_any(COMMERCIAL_HARD_REJECTS, title):
            return False
        return count_hits(CYBER_CONTEXT_PATTERNS, full) >= 1

    # Tier 2 — generic entry keywords in title + cyber context in body
    _ENTRY_TITLE = ["intern", "internship", "trainee", "graduate",
                    "entry level", "entry-level", "fresh grad", "new grad"]
    if has_any(_ENTRY_TITLE, title):
        if has_any(COMMERCIAL_HARD_REJECTS, title):
            return False
        return count_hits(CYBER_CONTEXT_PATTERNS, full) >= 2

    # Tier 3 — "junior" + any security term in title
    if has_any(["junior"], title) and has_any(
        ["security", "cyber", "soc", "grc", "pentest", "penetration",
         "appsec", "application security", "network security", "infosec",
         "information security", "cloud security", "siem"], title
    ):
        if has_any(COMMERCIAL_HARD_REJECTS, title):
            return False
        return count_hits(CYBER_CONTEXT_PATTERNS, full) >= 2

    # Tier 4 — entry signal anywhere in full text + security word in title (conservative)
    has_entry_in_body = bool(ENTRY_RE.search(full))
    if has_entry_in_body and has_any(
        ["security", "cyber", "infosec", "soc", "grc"], title
    ):
        if has_any(COMMERCIAL_HARD_REJECTS, title):
            return False
        return count_hits(CYBER_CONTEXT_PATTERNS, full) >= 3

    return False


def classify_cyber_intent(job: Any, *, use_llm: bool = True) -> CyberIntentDecision:
    """Primary cyber-intent gate.  Returns an accept/reject decision with confidence."""
    from intelligence.domain import classify_domain
    from intelligence.llm_classifier import classify_borderline_with_llm

    title = job_title(job)
    full = job_full_text(job)
    reasons: list[str] = []

    if not title:
        return CyberIntentDecision(False, "reject_missing_title", 0.0, ["missing_title"])

    reject_reason = hard_reject_reason(job)
    if reject_reason:
        return CyberIntentDecision(False, reject_reason, 0.0, [reject_reason])

    domain = classify_domain(job)
    title_hits = count_hits(STRONG_TITLE_PATTERNS, title)
    full_hits = count_hits(CYBER_CONTEXT_PATTERNS, full)

    if domain and title_hits >= 1:
        reasons.extend([f"domain:{domain}", "title_anchor"])
        return CyberIntentDecision(True, "accept_domain_title_anchor", 0.95, reasons)

    if domain and full_hits >= 2:
        reasons.extend([f"domain:{domain}", f"context_hits:{full_hits}"])
        return CyberIntentDecision(True, "accept_domain_context", 0.88, reasons)

    if has_any(["cybersecurity", "cyber security", "information security", "infosec"], title):
        reasons.append("broad_cyber_title")
        return CyberIntentDecision(True, "accept_broad_cyber_title", 0.86, reasons)

    if full_hits >= 4 and has_any(
        ["security", "cyber", "soc", "siem", "grc"], title + " " + full[:300]
    ):
        # ✅ v46: raised threshold from 3 → 4 hits to reduce false positives
        reasons.append(f"context_hits:{full_hits}")
        return CyberIntentDecision(True, "accept_context_stack", 0.82, reasons)

    borderline = has_any(
        ["security", "cyber", "risk", "privacy", "protection"], title + " " + full[:250]
    )
    if borderline and use_llm:
        llm_result = classify_borderline_with_llm(job)
        if llm_result is False:
            return CyberIntentDecision(
                False, "reject_llm_borderline", 0.20, ["llm_reject"], borderline=True
            )
        # A positive LLM opinion is not sufficient publish evidence.  It is
        # retained in the reason trail and falls through to strict rejection.
        if llm_result is True:
            reasons.append("llm_positive_not_publish_evidence")

    reason = (
        "reject_borderline_without_strong_anchor"
        if borderline
        else "reject_no_cyber_signal"
    )
    return CyberIntentDecision(
        False, reason, 0.25 if borderline else 0.05, [reason], borderline=borderline
    )
