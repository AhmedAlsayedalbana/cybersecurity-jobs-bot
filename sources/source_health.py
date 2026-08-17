"""Source health tracking and yield scoring.

Tracks per-source health metrics across runs to enable:
  - Zero-source diagnostics (why did this source return 0 jobs?)
  - Yield-based source prioritisation
  - Consecutive-failure circuit breaking
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class SourceHealthRecord:
    source_key: str
    runs_attempted: int = 0
    runs_healthy: int = 0
    runs_empty: int = 0
    runs_blocked: int = 0
    runs_parse_changed: int = 0
    runs_timeout: int = 0
    runs_not_configured: int = 0
    total_jobs_found: int = 0
    total_jobs_parsed: int = 0
    total_unique_jobs: int = 0
    total_duplicate_jobs: int = 0
    total_fresh_jobs: int = 0
    total_cyber_candidates: int = 0
    total_accepted_jobs: int = 0
    last_status: str = "unknown"
    last_run_ts: float = 0.0
    consecutive_failures: int = 0


_SOURCE_HEALTH: dict[str, SourceHealthRecord] = {}


def record_source_run(
    source_key: str,
    status: str,
    jobs_count: int = 0,
    *,
    error_code: str = "",
) -> None:
    """Record a source run result for health tracking."""
    if source_key not in _SOURCE_HEALTH:
        _SOURCE_HEALTH[source_key] = SourceHealthRecord(source_key=source_key)
    rec = _SOURCE_HEALTH[source_key]
    rec.runs_attempted += 1
    rec.last_status = status
    rec.last_run_ts = time.time()

    if status == "success":
        rec.runs_healthy += 1
        rec.total_jobs_found += jobs_count
        rec.consecutive_failures = 0
    elif status == "empty":
        rec.runs_empty += 1
        # empty is not a failure — don't increment consecutive_failures
    elif status == "blocked":
        rec.runs_blocked += 1
        rec.consecutive_failures += 1
    elif status == "parse_changed":
        rec.runs_parse_changed += 1
        rec.consecutive_failures += 1
    elif status == "timeout":
        rec.runs_timeout += 1
        rec.consecutive_failures += 1
    elif status in ("not_configured", "no_public_client_feed"):
        rec.runs_not_configured += 1


def get_source_health() -> dict[str, dict]:
    """Return snapshot of all source health records."""
    return {
        key: {
            "runs_attempted": rec.runs_attempted,
            "runs_healthy": rec.runs_healthy,
            "runs_empty": rec.runs_empty,
            "runs_blocked": rec.runs_blocked,
            "runs_parse_changed": rec.runs_parse_changed,
            "runs_timeout": rec.runs_timeout,
            "runs_not_configured": rec.runs_not_configured,
            "total_jobs_found": rec.total_jobs_found,
            "consecutive_failures": rec.consecutive_failures,
            "last_status": rec.last_status,
            "health_rate": round(rec.runs_healthy / max(1, rec.runs_attempted), 2),
        }
        for key, rec in _SOURCE_HEALTH.items()
    }


def classify_zero_reason(
    source_key: str,
    status: str,
    error_code: str = "",
) -> str:
    """Classify the specific reason for a 0-jobs result.

    Returns one of: EMPTY_REAL, PARSE_CHANGED, BLOCKED, TIMEOUT,
    NOT_CONFIGURED, NO_PUBLIC_FEED, NO_MATCHING_SECURITY_LISTINGS,
    SKIPPED_BUDGET
    """
    if status == "blocked" or "403" in error_code or "401" in error_code or "429" in error_code:
        return "BLOCKED"
    if status == "timeout":
        return "TIMEOUT"
    if status == "not_configured":
        return "NOT_CONFIGURED"
    if status == "no_public_client_feed":
        return "NO_PUBLIC_FEED"
    if error_code in ("no_matching_security_listings",):
        return "NO_MATCHING_SECURITY_LISTINGS"
    if status == "parse_changed":
        return "PARSE_CHANGED"
    if status == "empty":
        return "EMPTY_REAL"
    return status.upper()


def get_zero_sources_report() -> list[dict]:
    """Report on all sources that returned 0 jobs with reasons."""
    report = []
    for key, rec in _SOURCE_HEALTH.items():
        if rec.total_jobs_found == 0 and rec.runs_attempted > 0:
            report.append({
                "source": key,
                "status": rec.last_status,
                "reason": classify_zero_reason(key, rec.last_status),
                "attempts": rec.runs_attempted,
                "consecutive_failures": rec.consecutive_failures,
            })
    return sorted(report, key=lambda x: x["source"])


def compute_source_yield_score(source_key: str) -> float:
    """Compute yield score for source prioritisation.

    Higher = better source.  Factors:
      - Fresh unique cyber-relevant jobs = positive
      - Duplicate-heavy = negative
      - Blocked / parse_changed frequently = negative

    Returns a float in [0, 100].  Unknown sources get a neutral 50.
    """
    if source_key not in _SOURCE_HEALTH:
        return 50.0  # Unknown source — neutral
    rec = _SOURCE_HEALTH[source_key]
    if rec.runs_attempted == 0:
        return 50.0

    score = 50.0
    # Health rate bonus
    health_rate = rec.runs_healthy / max(1, rec.runs_attempted)
    score += health_rate * 20
    # Consecutive failure penalty
    score -= min(40, rec.consecutive_failures * 10)
    # Jobs found bonus (diminishing returns)
    score += min(20, rec.total_jobs_found * 0.5)

    return max(0, min(100, score))
