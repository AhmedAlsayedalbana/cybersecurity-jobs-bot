"""
job_intelligence.py
====================
Backward-compatible façade.

All logic has been moved into the ``intelligence/`` sub-package.
This module re-exports everything so that existing callers
(models.py, scoring.py, main.py, telegram_sender.py, tests/)
continue to work without modification.

DO NOT add new logic here.  Extend the relevant submodule instead.
"""

from __future__ import annotations

# Re-export the full public surface of the old module.
from intelligence import (  # noqa: F401  (re-exports)
    CyberIntentDecision,
    RoleDecision,
    are_duplicate_jobs,
    build_final_pool,
    classify_borderline_with_llm,
    classify_cyber_intent,
    classify_domain,
    classify_role,
    classify_geo,
    classify_level,
    classify_location,
    fuzzy_match,
    hard_reject_reason,
    has_strong_cyber_anchor,
    is_entry_level,
    is_remote_job,
    is_stale,
    is_true_security_internship,
    job_fingerprint,
    normalize_url,
)

# Legacy alias kept for any caller using the old name directly.
from intelligence._text import (  # noqa: F401
    count_hits as _count_hits,
    flatten_tags as _flatten_tags,
    has_any as _has_any,
    job_full_text as _full_text,
    norm as _norm,
    phrase_match,
)


def is_linkedin_job(job) -> bool:
    """Return True when the job originates from any LinkedIn source."""
    source = (
        getattr(job, "source_key", "") or getattr(job, "source", "") or ""
    ).strip().lower()
    return source.startswith("linkedin") or "linkedin" in source
