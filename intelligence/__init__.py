"""
intelligence/__init__.py
=========================
Public façade for the intelligence sub-package.

Import from here rather than individual submodules to keep internal
organization changeable without touching callers.

Usage:
    from intelligence import (
        classify_geo, classify_location, is_remote_job,
        classify_level, is_entry_level,
        classify_domain,
        classify_cyber_intent, hard_reject_reason, has_strong_cyber_anchor,
        is_true_security_internship, CyberIntentDecision,
        classify_borderline_with_llm,
        build_final_pool, is_stale,
        job_fingerprint, fuzzy_match, are_duplicate_jobs, normalize_url,
    )
"""

from intelligence.geo import classify_geo, classify_location, is_remote_job
from intelligence.seniority import classify_level, is_entry_level
from intelligence.domain import classify_domain
from intelligence.intent import (
    CyberIntentDecision,
    classify_cyber_intent,
    hard_reject_reason,
    has_strong_cyber_anchor,
    is_true_security_internship,
)
from intelligence.llm_classifier import classify_borderline_with_llm
from intelligence.pool_builder import build_final_pool, is_stale
from intelligence.dedupe import (
    are_duplicate_jobs,
    fuzzy_match,
    job_fingerprint,
    normalize_url,
)

__all__ = [
    # Geo
    "classify_geo",
    "classify_location",
    "is_remote_job",
    # Seniority
    "classify_level",
    "is_entry_level",
    # Domain
    "classify_domain",
    # Cyber intent
    "CyberIntentDecision",
    "classify_cyber_intent",
    "hard_reject_reason",
    "has_strong_cyber_anchor",
    "is_true_security_internship",
    # LLM
    "classify_borderline_with_llm",
    # Pool
    "build_final_pool",
    "is_stale",
    # Dedup helpers
    "are_duplicate_jobs",
    "fuzzy_match",
    "job_fingerprint",
    "normalize_url",
]
