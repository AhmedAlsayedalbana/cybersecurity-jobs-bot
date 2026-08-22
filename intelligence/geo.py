"""One strict, shared geographic policy for discovery and delivery.

Discovery may retain a query hint for telemetry. Delivery never may: an
explicit remote signal is worldwide; every other deliverable vacancy must
prove a physical/hybrid location in Egypt or an Arab country.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import config
from intelligence._text import has_any, job_tags, norm

_REMOTE_PATTERNS: frozenset[str] = frozenset(config.REMOTE_PATTERNS)
_EGYPT_ARABIC_PATTERNS: frozenset[str] = frozenset({
    "مصر", "القاهرة", "الجيزة", "الإسكندرية", "اسكندرية", "الإسكندريه",
    "اسكندريه", "الاسكندرية", "الاسكندريه", "القاهره", "الجيزه",
})
_HYBRID_PATTERNS: frozenset[str] = frozenset({
    "hybrid", "on-site", "onsite", "in office", "office based",
})
_UNRESOLVED_LOCATIONS: frozenset[str] = frozenset({
    "", "unknown", "not specified", "not available", "n/a", "na", "none",
    "location not specified", "anywhere",
})

# A safety list for titles that conflict with a source query stamp (for example
# an Egypt search result carrying ``Bangkok Based`` in its title). Arab-country
# matching itself remains centrally owned by config.ARAB_PATTERNS.
_OUTSIDE_REGION_LOCATION_MARKERS: frozenset[str] = frozenset({
    "bangkok", "thailand", "mexico", "mexico city", "united states", "usa",
    "u.s.", "canada", "london", "united kingdom", "uk", "germany", "berlin",
    "france", "paris", "spain", "italy", "netherlands", "sweden", "poland",
    "ireland", "portugal", "switzerland", "australia", "singapore", "india",
    "japan", "china", "hong kong", "philippines", "malaysia", "indonesia",
    "brazil", "argentina", "chile", "south africa", "nigeria", "kenya",
})


@dataclass(frozen=True, slots=True)
class DeliveryLocation:
    """Auditable final location decision used at every delivery boundary."""

    geo: str                       # egypt | arab | remote | global
    location_type: str             # physical | hybrid | remote | unknown
    normalized_country: str
    reason_code: str

    @property
    def eligible(self) -> bool:
        # v78: Global jobs are now eligible for delivery (routed to remote channel).
        return self.geo in {"egypt", "arab", "remote", "global"}


def _has_hybrid_marker(job: Any) -> bool:
    return has_any(_HYBRID_PATTERNS, " ".join([
        getattr(job, "location", "") or "",
        getattr(job, "job_type", "") or "",
        job_tags(job),
    ]))


def _has_explicit_remote_marker(job: Any) -> bool:
    """Only role-level remote data is sufficient; description prose is not."""
    if getattr(job, "is_remote", False):
        return True
    return has_any(_REMOTE_PATTERNS, " ".join([
        getattr(job, "title", "") or "",
        getattr(job, "location", "") or "",
        getattr(job, "job_type", "") or "",
        job_tags(job),
    ]))


def is_remote_job(job: Any) -> bool:
    """Hybrid is physical even where a board also advertises remote work."""
    return not _has_hybrid_marker(job) and _has_explicit_remote_marker(job)


def _country_from_text(text: str) -> tuple[str, str] | None:
    """Return (geo, normalized country/region) from authoritative text."""
    if has_any(config.EGYPT_PATTERNS, text) or has_any(_EGYPT_ARABIC_PATTERNS, text):
        return "egypt", "Egypt"
    if has_any(config.ARAB_PATTERNS, text):
        for marker in config.ARAB_PATTERNS:
            if marker and marker in text:
                return "arab", marker.title()
        return "arab", "Arab region"
    if has_any(_OUTSIDE_REGION_LOCATION_MARKERS, text):
        for marker in _OUTSIDE_REGION_LOCATION_MARKERS:
            if marker and marker in text:
                return "global", marker.title()
    return None


def resolve_delivery_location(job: Any) -> DeliveryLocation:
    """Resolve delivery location without using query/source geo hints."""
    if is_remote_job(job):
        return DeliveryLocation("remote", "remote", "Worldwide", "remote_worldwide")

    loc = norm(getattr(job, "location", "") or "")
    title = norm(getattr(job, "title", "") or "")
    location_type = "hybrid" if _has_hybrid_marker(job) else "physical"
    title_country = _country_from_text(title)
    location_country = _country_from_text(loc)

    # An explicit foreign title location is safety-critical when a source has
    # overwritten ``job.location`` with the regional search lane.
    if title_country and title_country[0] == "global":
        reason = "hybrid_outside_region" if location_type == "hybrid" else "physical_outside_region"
        return DeliveryLocation("global", location_type, title_country[1], reason)
    if location_country and location_country[0] == "global":
        reason = "hybrid_outside_region" if location_type == "hybrid" else "physical_outside_region"
        return DeliveryLocation("global", location_type, location_country[1], reason)
    if location_country:
        return DeliveryLocation(location_country[0], location_type, location_country[1], "location_match")
    if title_country:
        return DeliveryLocation(title_country[0], location_type, title_country[1], "title_location_match")
    if loc in _UNRESOLVED_LOCATIONS:
        return DeliveryLocation("global", "unknown", "", "unknown_location")

    reason = "hybrid_outside_region" if location_type == "hybrid" else "physical_outside_region"
    return DeliveryLocation("global", location_type, loc.title()[:80], reason)


def classify_delivery_geo(job: Any) -> str:
    """Backward-compatible strict delivery bucket."""
    return resolve_delivery_location(job).geo


def validate_location_for_channel(job: Any, channel: str) -> tuple[bool, DeliveryLocation]:
    """Final router/send check, returning both the verdict and audit fields."""
    decision = resolve_delivery_location(job)
    if not decision.eligible:
        return False, decision
    if channel == "egypt":
        return decision.geo == "egypt", decision
    if channel in {"gulf", "arab"}:  # ``gulf`` remains the legacy channel key.
        return decision.geo == "arab", decision
    if channel == "remote":
        # v78: Remote channel now accepts global physical jobs as a discovery layer.
        return decision.geo in ("remote", "global"), decision
    # Specialty channels accept only jobs that have already passed the shared
    # Egypt/Arab physical or explicit-worldwide-remote policy.
    return True, decision


def classify_geo(job: Any) -> str:
    """Discovery-only bucket; source hints can explain discovery, never delivery."""
    strict = classify_delivery_geo(job)
    if strict != "global":
        return strict
    loc = norm(getattr(job, "location", "") or "")
    if loc not in _UNRESOLVED_LOCATIONS:
        return "global"
    tags = job_tags(job)
    geo_hint = norm(getattr(job, "geo_hint", "") or "")
    if has_any(config.EGYPT_PATTERNS, tags) or has_any(_EGYPT_ARABIC_PATTERNS, tags):
        return "egypt"
    if has_any(config.ARAB_PATTERNS, tags):
        return "arab"
    if geo_hint == "egypt":
        return "egypt"
    if geo_hint in {"arab", "gulf", "ksa"}:
        return "arab"
    description = norm(getattr(job, "description", "") or "")
    if has_any(config.EGYPT_PATTERNS, description) or has_any(_EGYPT_ARABIC_PATTERNS, description):
        return "egypt"
    if has_any(config.ARAB_PATTERNS, description):
        return "arab"
    return "global"


def classify_location(job: Any) -> str:
    geo = classify_geo(job)
    return geo if geo in {"egypt", "arab"} else "global"
