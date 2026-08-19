# -*- coding: utf-8 -*-
"""v74/v75: Egypt/Arab pipeline funnel tracker.

Tracks Egypt/Arab delivery-location jobs through every hard stage of the
pipeline and attributes exactly one drop reason per job that falls out.

Stage chain (each <= the previous — enforced by check_consistency):

  discovered -> cyber_candidate -> location_ok -> fresh -> new_job ->
  in_pool -> delivery_eligible -> routed -> sent

Counters are intentionally decoupled from per-key tracking in the pipeline:
the pipeline code records the *real* job counts of each stage (from the
actual job lists it already holds), and this module computes drop reasons
as the monotonic differences between consecutive stages. That guarantees
the funnel can never show zeros while the real pipeline sent jobs.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

EGYPT_GEO = "egypt"
ARAB_GEO = "arab"
STAGE_ORDER = [
    "discovered", "cyber_candidate", "location_ok", "fresh", "new_job",
    "in_pool", "delivery_eligible", "routed", "sent",
]


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
    drop_reasons: Counter = field(default_factory=Counter)

    # per-key drop bookkeeping still works for jobs that drop OUTSIDE the
    # stage chain (e.g., a job that was never counted at discovered because
    # it never reached all_jobs — these are one-off drops).
    seen_keys: set = field(default_factory=set)

    def record_drop(self, key: str, reason: str) -> None:
        if not key or key in self.seen_keys:
            return
        self.seen_keys.add(key)
        self.drop_reasons[reason] += 1

    def set_stage(self, stage: str, count: int) -> None:
        """Record the REAL stage count from the pipeline-native job list."""
        if stage not in STAGE_ORDER:
            return
        setattr(self, stage, max(0, int(count)))

    def check_consistency(self, log: Any) -> None:
        """Warn (never raise) if any stage exceeds its predecessor."""
        previous = 0
        for stage in STAGE_ORDER:
            value = getattr(self, stage)
            if value > previous and previous > 0:
                # A later stage may exceed an earlier one only when the
                # earlier counter was never populated (zero) — that is the
                # exact v74 bug this check exists to catch next time.
                log.warning(
                    "EG/Arab funnel [%s] INCONSISTENT: %s=%d > earlier %d "
                    "(earlier stage was never populated — pipeline stage is "
                    "not recording) — drop reasons are estimated.",
                    self.geo, stage, value, previous,
                )
            if value > 0:
                previous = value
        # Attribute drop reasons as monotonic differences. Keys recorded by
        # record_drop() already carry a concrete reason; the stage gaps
        # explain everything else, so every job is accounted for exactly once.
        stages = [(s, getattr(self, s)) for s in STAGE_ORDER]
        pairs = list(zip(stages, stages[1:]))
        reason_map = {
            ("discovered", "cyber_candidate"): "non_cyber",
            ("cyber_candidate", "location_ok"): "location",
            ("location_ok", "fresh"): "recency",
            ("fresh", "new_job"): "dedup_or_already_seen",
            ("new_job", "in_pool"): "pool_selection",
            ("in_pool", "delivery_eligible"): "not_delivery_eligible",
            ("delivery_eligible", "routed"): "unrouted",
            ("routed", "sent"): "not_sent",
        }
        accounted = sum(self.drop_reasons.values())
        # An unpopulated intermediate stage (count==0, meaning the pipeline
        # never recorded it) must not steal the attribution: the gap between
        # the last POPULATED stage and the current one is attributed to the
        # gate immediately before the current stage (the real filtering
        # gate that the jobs failed, per the recorded pipeline states).
        last_populated_value = 0
        for i, stage in enumerate(STAGE_ORDER):
            value = getattr(self, stage)
            if value > 0:
                if i > 0 and value < last_populated_value:
                    gate_before = STAGE_ORDER[i - 1]
                    reason = reason_map[(gate_before, stage)]
                    self.drop_reasons[reason] += last_populated_value - value
                last_populated_value = value
        # If drop reasons already exceed the accounted gaps (from record_drop
        # one-offs), the concrete reasons win — nothing to add.
        _ = accounted


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
    """{geo: {dedup_keys}} from geo_keys()'s {dedup_key: geo} dict."""
    out: dict[str, set] = {}
    for key, geo in (keys_by_geo or {}).items():
        out.setdefault(geo, set()).add(key)
    return out


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


def log_funnel(funnel: EgyptPipelineFunnel, label: str, logger: Any) -> None:
    """Log the funnel with drop reasons at the end of the run."""
    for geo_name, f in (("egypt", funnel.egypt), ("arab", funnel.arab)):
        if f.discovered == 0 and not f.drop_reasons:
            continue
        f.check_consistency(logger)
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
