# -*- coding: utf-8 -*-
"""v74: Egypt/Arab pipeline funnel tracker.

Tracks jobs whose delivery location is Egypt (or Arab) through every
hard stage of the pipeline and records the reason each one drops out.

Stages tracked per job (dedup_key):
  discovered      — the job was emitted by any source and reached the pool
                    assembly step with an Egypt/Arab delivery location.
  cyber_candidate — passed the cyber verdict (CONFIRMED/LIKELY).
  location_ok     — passed the physical-location gate.
  fresh           — passed the recency gate.
  new_job         — passed exact-identity dedup (not previously sent/seen).
  in_pool         — selected by pool_builder (fresh-first, ratio, threshold).
  delivery_eligible — reached Telegram delivery eligibility.
  routed_egypt    — matched the Egypt channel (or any Arab channel for the
                    parallel arab funnel).
  sent            — actually posted to the Telegram channel this run.

Only drop reasons are counted (never double counted — each job records at
most one drop reason per funnel), and jobs that pass every stage are counted
in ``sent``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

EGYPT_GEO = "egypt"
ARAB_GEO = "arab"


@dataclass
class _EgyptFunnel:
    geo: str
    discovered: int = 0
    cyber_candidate: int = 0
    location_ok: int = 0
    fresh: int = 0
    new_job: int = 0
    in_pool: int = 0
    delivery_eligible: int = 0
    routed: int = 0
    sent: int = 0
    seen_keys: set = field(default_factory=set)
    drop_reasons: Counter = field(default_factory=Counter)

    def record_drop(self, key: str, reason: str) -> None:
        if not key or key in self.seen_keys:
            return
        self.seen_keys.add(key)
        self.drop_reasons[reason] += 1

    def record_stage(self, key: str, stage: str) -> None:
        if not key:
            return
        if key in self.seen_keys:
            return  # already dropped or finished
        self.seen_keys.add(key)
        setattr(self, stage, getattr(self, stage) + 1)


@dataclass
class EgyptPipelineFunnel:
    """Egypt and Arab delivery-location funnels (separate counters)."""

    egypt: _EgyptFunnel = field(default_factory=lambda: _EgyptFunnel(EGYPT_GEO))
    arab: _EgyptFunnel = field(default_factory=lambda: _EgyptFunnel(ARAB_GEO))

    def funnel_for(self, geo: str) -> _EgyptFunnel | None:
        if geo == EGYPT_GEO:
            return self.egypt
        if geo == ARAB_GEO:
            return self.arab
        return None


def _geo_of(job: Any) -> str:
    """Delivery geo bucket for a job (same semantics as the location gate)."""
    from intelligence.geo import classify_delivery_geo
    return classify_delivery_geo(job) or ""


def geo_keys(jobs: Iterable[Any]) -> dict:
    """{dedup_key: geo} for non-Egypt/non-Arab keys are excluded."""
    out: dict[str, str] = {}
    for job in jobs:
        key = getattr(job, "dedup_key", "") or ""
        if not key:
            continue
        geo = _geo_of(job)
        if geo in (EGYPT_GEO, ARAB_GEO):
            out.setdefault(key, geo)
    return out


def stage_keys(keys_by_geo: dict) -> dict:
    """Split {key: geo} into per-funnel key sets."""
    return {
        EGYPT_GEO: {k for k, g in keys_by_geo.items() if g == EGYPT_GEO},
        ARAB_GEO: {k for k, g in keys_by_geo.items() if g == ARAB_GEO},
    }


def log_funnel(funnel: EgyptPipelineFunnel, label: str, logger: Any) -> None:
    """Log the funnel with drop reasons at the end of the run."""
    for geo_name, f in (("egypt", funnel.egypt), ("arab", funnel.arab)):
        if f.discovered == 0 and not f.drop_reasons:
            continue
        reasons = ", ".join(
            f"{reason}={count}" for reason, count in f.drop_reasons.most_common()
        ) or "none"
        logger.info(
            "🇪🇬 %s funnel [%s]: discovered=%d cyber_candidate=%d location_ok=%d "
            "fresh=%d new=%d in_pool=%d delivery_eligible=%d routed=%d sent=%d "
            "dropped=%s",
            label, geo_name, f.discovered, f.cyber_candidate, f.location_ok,
            f.fresh, f.new_job, f.in_pool, f.delivery_eligible, f.routed,
            f.sent, reasons,
        )
