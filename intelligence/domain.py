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

# A description can explain a genuine cyber role, but it must not alone route
# a generic "Solutions Engineer" / "Cloud Engineer" / "Remote" role into a
# specialist Telegram topic. These are explicit role anchors, deliberately
# excluding vague terms such as cloud, solutions, engineer, and remote.
_CYBER_ROLE_TITLE_ANCHORS: tuple[str, ...] = (
    "security engineer", "security analyst", "security architect",
    "security operations", "information security", "it security",
    "cybersecurity", "cyber security", "infosec",
    "soc", "pentest", "penetration test", "red team", "appsec", "devsecops",
    "network security", "identity access", "identity and access",
    "access management", "iam engineer", "security auditor", "grc",
)

# CloudSec is deliberately stricter than broad domain classification. Product
# names, a cloud employer, or generic engineering language cannot establish a
# CloudSec route; one of these actual cloud-security controls/domains must be
# present in addition to the normal role-context checks below.
_CLOUDSEC_CHANNEL_EVIDENCE: tuple[str, ...] = (
    "cloud security", "aws security", "azure security", "gcp security",
    "cnapp", "cspm", "cwpp", "cloud iam", "cloud identity and access management",
    "cloud infrastructure security", "cloud and infrastructure security",
    "cloud & infrastructure security", "kubernetes security", "container security",
    "cloud threat detection", "cloud siem", "cloud workload protection",
)

_EDUCATION_TITLE_MARKERS: tuple[str, ...] = (
    "instructor", "trainer", "training", "teacher", "lecturer",
    "professor", "faculty", "teaching", "curriculum",
)


def _is_education_position(job: Any) -> bool:
    """Training roles can be cyber jobs, but are not SOC/AppSec vacancies.

    Their descriptions naturally name every technology taught, so allowing
    description-only specialty matching would falsely send one instructor post
    to several technical channels.  They may still go to their valid geo lane.
    """
    return has_any(_EDUCATION_TITLE_MARKERS, job_title(job))


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


def has_channel_evidence(job: Any, domain: str | None) -> bool:
    """Return whether a specialty channel has publish-grade cyber evidence.

    Domain classification may use the description to help rank a role. Channel
    delivery is stricter: a domain phrase must occur in the title/tags, or a
    recognised cyber role must appear in the title/tags alongside domain
    evidence in the description. Generic commercial roles therefore remain
    eligible for their geographic channel, but cannot leak into CloudSec (or
    another specialty topic) merely because the job description mentions a
    product, cloud, solutions, engineering, or remote work.
    """
    if domain == "internships":
        from intelligence.intent import is_true_security_internship

        return is_true_security_internship(job)
    if domain not in DOMAIN_PATTERNS:
        return False

    if _is_education_position(job):
        return False

    title_tags = f"{job_title(job)} {job_tags(job)}".strip()
    domain_patterns = (
        _CLOUDSEC_CHANNEL_EVIDENCE
        if domain == "cloudsec"
        else DOMAIN_PATTERNS[domain]
    )
    if has_any(domain_patterns, title_tags):
        return True

    # Context is admissible only after the title itself establishes that this
    # is a cybersecurity role. This prevents description-only false routing.
    if not has_any(_CYBER_ROLE_TITLE_ANCHORS, title_tags):
        return False
    broad = f"{title_tags} {job_description(job, limit=500)}"
    return has_any(domain_patterns, broad)
