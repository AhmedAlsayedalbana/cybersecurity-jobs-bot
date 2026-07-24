"""
intelligence/pool_builder.py
=============================
Final job pool construction with LinkedIn cap, entry-level target,
non-LinkedIn floor, and geo-priority ordering.

Extracted from main.py so it can be tested in isolation and reused.

Public API:
    build_final_pool(jobs, score_fn) → list[Job]
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Callable

import config
from intelligence.geo import classify_geo
from intelligence.seniority import is_entry_level

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Staleness gate
# ---------------------------------------------------------------------------

def is_stale(job: Any) -> bool:
    """Hard-block jobs older than MAX_JOB_AGE_DAYS (default: 2 days).

    Rules (in order):
      1. If posted_date is set → use it directly.
      2. If 'X days ago' / 'X weeks ago' text found → use inferred age.
      3. If source is Greenhouse Expanded with no date → treat as fresh
         (greenhouse sets created_at from API, so missing = very recent).
      4. All other jobs with no date → treat as fresh (pass through).
    """
    posted = getattr(job, "posted_date", None)
    if posted:
        # Normalize tz-aware to naive
        if getattr(posted, "tzinfo", None) is not None:
            from datetime import timezone
            posted = posted.astimezone(timezone.utc).replace(tzinfo=None)
        return datetime.now() - posted >= timedelta(days=config.MAX_JOB_AGE_DAYS)

    age_text = " ".join([
        getattr(job, "title", "") or "",
        getattr(job, "description", "") or "",
        " ".join(str(t) for t in (getattr(job, "tags", []) or [])),
    ]).lower()

    m_days = re.search(r"\b(\d{1,2})\s*(?:day|days|d)\s*ago\b", age_text)
    if m_days and int(m_days.group(1)) >= config.MAX_JOB_AGE_DAYS:
        return True
    m_weeks = re.search(r"\b(\d{1,2})\s*(?:week|weeks|w)\s*ago\b", age_text)
    if m_weeks and (int(m_weeks.group(1)) * 7) >= config.MAX_JOB_AGE_DAYS:
        return True
    m_months = re.search(r"\b(\d{1,2})\s*(?:month|months|mo)\s*ago\b", age_text)
    if m_months:
        return True   # any month-old job is stale

    return False


# ---------------------------------------------------------------------------
# Ordering helpers
# ---------------------------------------------------------------------------

_GEO_RANK: dict[str, int] = {
    "egypt": 0, "ksa": 1, "gulf_other": 2, "remote": 3, "global": 4
}


def _geo_rank(job: Any) -> int:
    return _GEO_RANK.get(classify_geo(job), 4)


def _is_linkedin(job: Any) -> bool:
    source = (getattr(job, "source_key", "") or getattr(job, "source", "") or "").lower()
    return source.startswith("linkedin") or "linkedin" in source


def _is_approved_secondary(job: Any) -> bool:
    """True for the ~20% non-LinkedIn allocation: Wazzif + well-known Egyptian
    boards + freelance platforms. Anything else (Greenhouse, Jina/Bayt-Gulf,
    Telegram, Reddit, JSearch, MENA/Gulf boards...) is low-priority filler."""
    source = (getattr(job, "source_key", "") or getattr(job, "source", "") or "").lower()
    return source in config.APPROVED_SECONDARY_SOURCE_KEYS


def _selection_key(job: Any) -> str:
    return (
        getattr(job, "dedup_key", "")
        or getattr(job, "url_id", "")
        or getattr(job, "url", "")
        or getattr(job, "unique_id", "")
    )


def _score_with_priority(job: Any, score_fn: Callable) -> int:
    """Apply origin_priority bonus to score."""
    score = score_fn(job)
    origin_priority = int(getattr(job, "origin_priority", 999) or 999)
    if origin_priority <= 25:
        score += 1
    return score


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_final_pool(jobs: list, score_fn: Callable) -> list:
    """Construct the final ordered job pool respecting all ratio constraints.

    Args:
        jobs:     All candidate job objects (post-dedup, post-filter).
        score_fn: Callable that takes a job and returns an integer score.

    Returns:
        Ordered list of selected jobs, up to MAX_JOBS_PER_RUN.

    Pool logic:
        1. Remove stale jobs.
        2. Score and geo-sort (egypt → ksa → gulf_other → remote → global).
        3. Apply SCORE_THRESHOLD gate (fallback to top-30 if none pass).
        4. Enforce:
            a. NON_LINKEDIN_POOL_FLOOR_RATIO  — protect source diversity
            b. ENTRY_LEVEL_TARGET_RATIO       — include entry-level jobs
            c. LINKEDIN_POOL_CAP_RATIO        — prevent LinkedIn dominance
        5. Fill remaining slots from highest-scoring qualified jobs.
    """
    rows = [
        (job, _score_with_priority(job, score_fn))
        for job in jobs
        if not is_stale(job)
    ]
    # Sort order: geo first (Egypt > Gulf > Remote > Global),
    # then source priority (LinkedIn=10 > Wuzzuf=15 > Freelance=21 > others),
    # then score descending.
    def _origin_priority(job: Any) -> int:
        return int(getattr(job, "origin_priority", 999) or 999)

    rows.sort(key=lambda item: (_geo_rank(item[0]), _origin_priority(item[0]), -item[1]))

    qualified = [item for item in rows if item[1] >= config.SCORE_THRESHOLD]
    if not qualified and rows:
        log.warning("⚠ No jobs passed score threshold — using top-30 fallback")
        qualified = rows[:30]

    pool_size = min(config.MAX_JOBS_PER_RUN, len(qualified))
    if pool_size <= 0:
        return []

    entry_available = sum(1 for job, _ in qualified if is_entry_level(job))
    approved_secondary_available = sum(1 for job, _ in qualified if _is_approved_secondary(job))
    non_linkedin_available = sum(1 for job, _ in qualified if not _is_linkedin(job))

    entry_target = min(
        entry_available, max(1, round(pool_size * config.ENTRY_LEVEL_TARGET_RATIO))
    )
    # The ~20% non-LinkedIn floor is filled ONLY from approved secondary
    # sources (Wazzif / Egyptian boards / freelance) — never from filler
    # sources like Greenhouse or Jina scraping.
    non_li_floor = min(
        approved_secondary_available, int(pool_size * config.NON_LINKEDIN_POOL_FLOOR_RATIO)
    )
    requested_li_cap = round(pool_size * config.LINKEDIN_POOL_CAP_RATIO)
    # When the available non-LinkedIn supply is lower than the requested 40%,
    # shrink the final pool instead of silently filling it with extra LinkedIn
    # jobs. This keeps the realized pool at or below the configured ratio.
    if config.LINKEDIN_POOL_CAP_RATIO >= 1:
        li_cap = requested_li_cap
    else:
        supply_li_cap = int(
            non_linkedin_available * config.LINKEDIN_POOL_CAP_RATIO
            / (1 - config.LINKEDIN_POOL_CAP_RATIO)
        )
        li_cap = min(requested_li_cap, supply_li_cap)

    selected: list = []
    selected_keys: set[str] = set()
    linkedin_count = 0

    def _selected_entry_count() -> int:
        return sum(1 for j in selected if is_entry_level(j))

    def _selected_non_li_count() -> int:
        return sum(1 for j in selected if not _is_linkedin(j))

    def _try_add(job: Any, *, enforce_li_cap: bool = True) -> bool:
        nonlocal linkedin_count
        key = _selection_key(job)
        if key in selected_keys:
            return False
        is_li = _is_linkedin(job)
        # v54 fix: li_cap (computed once from pool_size * LINKEDIN_POOL_CAP_RATIO)
        # used to be calculated but never actually enforced here — this method
        # recomputed a separate "dynamic" cap off the incrementally-growing
        # selection length instead, which drifted well below the real target
        # (observed ~70% instead of the configured 80%). Now it enforces the
        # real li_cap directly.
        if enforce_li_cap and is_li and linkedin_count + 1 > li_cap:
            return False
        selected.append(job)
        selected_keys.add(key)
        if is_li:
            linkedin_count += 1
        return True

    # Phase 1: Protect the ~20% non-LinkedIn floor — approved secondary
    # sources ONLY (Wazzif / Egyptian boards / freelance). Filler sources
    # (Greenhouse, Jina, Telegram, Reddit, JSearch...) are excluded here.
    for job, _ in qualified:
        if len(selected) >= pool_size or _selected_non_li_count() >= non_li_floor:
            break
        if _is_approved_secondary(job):
            _try_add(job)

    # Phase 2: Fill entry-level target.
    for job, _ in qualified:
        if len(selected) >= pool_size or _selected_entry_count() >= entry_target:
            break
        if is_entry_level(job):
            _try_add(job)

    # Phase 3: Fill remaining slots — LinkedIn and approved secondary
    # sources first (this is where LinkedIn reaches its ~80% share).
    for job, _ in qualified:
        if len(selected) >= pool_size:
            break
        if _is_linkedin(job) or _is_approved_secondary(job):
            _try_add(job)

    # Phase 4: Only if LinkedIn + approved secondary couldn't fill the pool,
    # fall back to filler sources (Greenhouse/Jina/Telegram/etc.) as a
    # last resort so the pool isn't left short.
    for job, _ in qualified:
        if len(selected) >= pool_size:
            break
        _try_add(job)

    min_pool_size = int(getattr(config, "MIN_POOL_SIZE", 5))
    if len(selected) < min_pool_size and len(qualified) >= min_pool_size:
        # Merged from official-sources' "relaxing quotas" behaviour, kept as a
        # last-resort safety net instead of the default path. In a healthy
        # run the ratio above already fills the pool; this only fires when
        # there genuinely isn't enough non-LinkedIn/secondary supply this
        # cycle, so a real shortage doesn't leave the channel silent. Because
        # it runs after — not instead of — the strict li_cap enforcement, the
        # 60/40 target from v58 stays intact on every normal run.
        log.warning(
            "Pool below minimum (%d < %d) — relaxing LinkedIn cap as last resort",
            len(selected),
            min_pool_size,
        )
        for job, _ in qualified:
            if len(selected) >= min_pool_size:
                break
            _try_add(job, enforce_li_cap=False)

    log.info(
        "Pool: %d jobs | LinkedIn: %d/%d | Entry: %d/%d | Non-LI: %d",
        len(selected), linkedin_count, li_cap,
        _selected_entry_count(), entry_target,
        _selected_non_li_count(),
    )
    return selected
