"""
intelligence/domain.py
======================
Canonical cybersecurity role and Telegram topic classification.

Public API:
    classify_role(job)   -> RoleDecision
    classify_domain(job) -> "pentest" | "soc" | "appsec" | "cloudsec" |
                            "networksec" | "grc" | "seceng" |
                            "internships" | None
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from intelligence._text import job_description, job_tags, job_title, phrase_match
from intelligence.patterns import ROLE_CLASSIFICATION_ORDER, ROLE_TAXONOMY


@dataclass(slots=True, frozen=True)
class RoleDecision:
    role_key: str
    parent: str
    channel_key: str
    confidence: float
    signals: list[str]


NO_ROLE = RoleDecision("", "", "", 0.0, [])


def _matching_signals(patterns: list[str], text: str) -> list[str]:
    return [pattern for pattern in patterns if phrase_match(pattern, text)]


def _decision(role_key: str, *, confidence: float, signals: list[str]) -> RoleDecision:
    spec = ROLE_TAXONOMY[role_key]
    return RoleDecision(
        role_key=role_key,
        parent=str(spec["parent"]),
        channel_key=str(spec["channel"]),
        confidence=confidence,
        signals=signals[:8],
    )


def classify_role(job: Any) -> RoleDecision:
    """Return the best professional cybersecurity role decision for a job.

    Title and tags are authoritative. Description is a lower-confidence fallback
    used only after no title/tag role signal exists.
    """
    from intelligence.intent import is_true_security_internship

    if is_true_security_internship(job):
        return RoleDecision(
            role_key="security_internship",
            parent="entry",
            channel_key="internships",
            confidence=0.98,
            signals=["true_security_internship"],
        )

    title_tags = f"{job_title(job)} {job_tags(job)}".strip()
    broad = f"{title_tags} {job_description(job, limit=500)}".strip()

    for role_key in ROLE_CLASSIFICATION_ORDER:
        patterns = list(ROLE_TAXONOMY[role_key]["patterns"])
        signals = _matching_signals(patterns, title_tags)
        if signals:
            return _decision(role_key, confidence=0.95, signals=signals)

    for role_key in ROLE_CLASSIFICATION_ORDER:
        patterns = list(ROLE_TAXONOMY[role_key]["patterns"])
        signals = _matching_signals(patterns, broad)
        if signals:
            return _decision(role_key, confidence=0.82, signals=signals)

    return NO_ROLE


def classify_domain(job: Any) -> str | None:
    """Backward-compatible Telegram topic domain key."""
    decision = classify_role(job)
    return decision.channel_key or None
