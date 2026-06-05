"""
intelligence/domain.py
======================
Domain / specialisation classification for cybersecurity roles.

Public API:
    classify_domain(job) → "pentest" | "soc" | "appsec" | "cloudsec" |
                           "networksec" | "grc" | "seceng" | "internships" | None
"""

from __future__ import annotations

from typing import Any

from intelligence._text import has_any, job_description, job_tags, job_title
from intelligence.patterns import DOMAIN_PATTERNS

# Resolution order: more specific domains win over generic seceng
_DOMAIN_ORDER = ["pentest", "soc", "appsec", "cloudsec", "networksec", "grc", "seceng"]


def classify_domain(job: Any) -> str | None:
    """Match the most specific cybersecurity domain.

    Resolution: title+tags (narrow) → description (broad).
    Internships are tested first via is_true_security_internship.
    """
    # Avoid circular import — import lazily
    from intelligence.intent import is_true_security_internship

    if is_true_security_internship(job):
        return "internships"

    title = job_title(job)
    tags = job_tags(job)
    desc = job_description(job, limit=320)
    title_tags = title + " " + tags
    broad = title_tags + " " + desc

    # Narrow match (title + tags only)
    for domain in _DOMAIN_ORDER:
        if has_any(DOMAIN_PATTERNS[domain], title_tags):
            return domain

    # Broad match (include description)
    for domain in _DOMAIN_ORDER:
        if has_any(DOMAIN_PATTERNS[domain], broad):
            return domain

    return None
