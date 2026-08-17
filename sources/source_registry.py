"""
sources/source_registry.py — Ultimate v50+

Merged source registry: MCO's comprehensive coverage + MCL's tier-based
priority architecture + dead-source documentation.

Priority order is owned by ``config.SOURCE_PRIORITY_BY_KEY``. LinkedIn is
always first, followed by official company careers, Greenhouse/direct ATS,
Indeed, the regional boards, freelance sites, remote boards, and discovery.

DISABLED (confirmed dead sources):
  ✗ linkedin_extended    (queries merged into linkedin_unified)
  ✗ google_intel_active  (SerpAPI 429 on every request)
  ✗ gulf_monster         (0 jobs on every run — feed changed)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import config
from sources.egypt_boards import fetch_wazzif
from sources.egypt_direct import fetch_careers_egypt
from sources.expanded_sources import fetch_expanded_sources
from sources.greenhouse_expanded import fetch_greenhouse_expanded
from sources.jsearch_enhanced import fetch_jsearch_enhanced
from sources.linkedin_unified import fetch_linkedin_unified_async
from sources.mena_boards import fetch_mena_boards
from sources.new_sources import _fetch_greenhouse_cybersec
from sources.tech_boards import fetch_tech_boards
from sources.recruitment_agencies import fetch_recruitment_agencies
from sources.arab_careers import fetch_arab_careers
from sources.marketplace_sources import PUBLIC_SPECS, RESTRICTED_SPECS, fetcher_for
from sources.official_careers import OFFICIAL_SOURCES, fetcher_for as official_fetcher_for
from sources.priority_sources import (
    fetch_google_intelligence,
    fetch_indeed_public,
    fetch_reddit_discord,
    fetch_telegram_channels,
)

# Optional AKM sources — gracefully absent if not installed
try:
    from sources.gulf_boards import fetch_gulf_boards
except ImportError:
    fetch_gulf_boards = None  # type: ignore[assignment]

try:
    from sources.linkedin_api import fetch_jsearch_linkedin
except ImportError:
    fetch_jsearch_linkedin = None  # type: ignore[assignment]


@dataclass(slots=True)
class SourceSpec:
    key: str
    name: str
    fetcher: Callable
    priority: int
    lane: str
    quality_tier: str = "standard"
    recency_required: bool = False
    allow_empty_runs: bool = False
    api_key_optional: bool = False
    unstable: bool = False
    enabled: bool = True
    supports_geo_hint: bool = False
    requires_login: bool = False
    source_timeout_seconds: float | None = None


def _build_specs() -> list[SourceSpec]:
    specs = [
        # ── TIER 1: LinkedIn (Priority #1) ──────────────────────────────────
        SourceSpec("linkedin_unified", "LinkedIn Unified",
            fetch_linkedin_unified_async, config.source_priority("linkedin_unified"), "core", "gold",
            recency_required=True),

        SourceSpec("egytech_fyi", "EgyTech.fyi",
            fetch_careers_egypt, config.source_priority("company_careers", 20), "egypt", "silver",
            recency_required=True, allow_empty_runs=True, supports_geo_hint=True,
            source_timeout_seconds=config.CAREERS_API_SOURCE_TIMEOUT_SECONDS),
        SourceSpec("indeed", "Indeed",
            fetch_indeed_public, config.source_priority("indeed"), "core", "silver",
            recency_required=True, allow_empty_runs=True),
        # ── TIER 4: Greenhouse / Cybersec Vendor Boards ──────────────────────
        SourceSpec("greenhouse_cybersec", "Greenhouse Cybersec",
            _fetch_greenhouse_cybersec, config.source_priority("greenhouse_cybersec"), "core", "gold",
            recency_required=True, allow_empty_runs=True,
            source_timeout_seconds=config.CAREERS_API_SOURCE_TIMEOUT_SECONDS),
        SourceSpec("greenhouse_expanded", "Greenhouse Expanded (Big Tech + SaaS)",
            fetch_greenhouse_expanded, config.source_priority("greenhouse_expanded"), "core", "silver",
            recency_required=True, allow_empty_runs=True,
            enabled=getattr(config, "ENABLE_SOURCE_GREENHOUSE_EXPANDED", True),
            source_timeout_seconds=config.CAREERS_API_SOURCE_TIMEOUT_SECONDS),

        # ── TIER 4b: AKM Expanded & Tech Boards ──────────────────────────────
        SourceSpec("expanded_sources", "AKM Expanded Sources",
            fetch_expanded_sources, 36, "core", "silver",
            recency_required=True, allow_empty_runs=True,
            enabled=getattr(config, "ENABLE_SOURCE_EXPANDED", True)),
        SourceSpec("tech_boards", "AKM Tech Boards",
            fetch_tech_boards, 37, "core", "silver",
            recency_required=True, allow_empty_runs=True,
            enabled=getattr(config, "ENABLE_SOURCE_TECH_BOARDS", True)),
        # ── TIER 5: Other MENA sources ────────────────────────────────────────
        SourceSpec("mena_boards", "MENA Boards (legacy dead boards skipped)",
            fetch_mena_boards, 40, "gulf", "silver",
            allow_empty_runs=True, supports_geo_hint=True,
            enabled=getattr(config, "ENABLE_SOURCE_MENA_BOARDS", True)),

        # Wazzif (وظف) is not covered anywhere else: mena_boards.py already
        # covers Akhtaboot/DrJobPro/Forasna/Tanqeeb/Wuzzuf-RSS (kept disabled
        # by default to avoid double-fetching those against
        # marketplace_sources.py), and Wazzif is outside that overlap — so
        # it is safe to register on its own without risking duplicate posts.
        SourceSpec("wazzif", "Wazzif (وظف)",
            fetch_wazzif, 41, "egypt", "silver",
            allow_empty_runs=True, supports_geo_hint=True,
            enabled=getattr(config, "ENABLE_SOURCE_WAZZIF", True)),

        # Arab company careers
        SourceSpec("arab_careers", "Arab Company Careers",
            fetch_arab_careers, 38, "gulf", "silver",
            allow_empty_runs=True, supports_geo_hint=True,
            enabled=getattr(config, "ENABLE_SOURCE_ARAB_CAREERS", True)),

        # Recruitment agencies
        SourceSpec("recruitment_agencies", "Recruitment Agencies (MENA)",
            fetch_recruitment_agencies, 39, "gulf", "bronze",
            allow_empty_runs=True, supports_geo_hint=True,
            enabled=getattr(config, "ENABLE_SOURCE_RECRUITMENT", True)),

        # ── TIER 7: Community ─────────────────────────────────────────────────
        SourceSpec("telegram_channels", "Telegram Channels",
            fetch_telegram_channels, 50, "community", "silver",
            recency_required=True, allow_empty_runs=True),
        SourceSpec("reddit_discord", "Reddit / Discord / GitHub Hiring",
            fetch_reddit_discord, 51, "community", "bronze",
            recency_required=True, allow_empty_runs=True),

        # ── TIER 8: RapidAPI (optional — needs RAPIDAPI_KEY) ──────────────────
        SourceSpec("jsearch_enhanced", "JSearch Enhanced (LinkedIn+Indeed via RapidAPI)",
            fetch_jsearch_enhanced, 65, "api", "silver",
            recency_required=True, allow_empty_runs=True, api_key_optional=True,
            enabled=getattr(config, "ENABLE_SOURCE_JSEARCH_ENHANCED", True),
            source_timeout_seconds=config.CAREERS_API_SOURCE_TIMEOUT_SECONDS),

        SourceSpec("google_intel", "Google Search Intelligence",
            fetch_google_intelligence, 90, "api", "bronze",
            recency_required=True, allow_empty_runs=True, api_key_optional=True,
            enabled=config.ENABLE_UNSTABLE_SOURCES,
            source_timeout_seconds=config.CAREERS_API_SOURCE_TIMEOUT_SECONDS),
    ]

    # v55 public marketplace/board catalog.  Each required platform is
    # registered exactly once, and carries its own direct -> Reader fallback
    # plus policy status.  Restricted service marketplaces intentionally return
    # no_public_client_feed rather than seller advertisements.
    for market in (*PUBLIC_SPECS, *RESTRICTED_SPECS):
        specs.append(SourceSpec(
            market.key,
            market.name,
            fetcher_for(market.key),
            config.source_priority(market.key, market.priority),
            "freelance" if market.content_type == "client_project" else ("egypt" if market.geo_hint == "egypt" else "gulf"),
            "silver" if market.supports_public_client_feed else "bronze",
            recency_required=market.supports_public_client_feed,
            allow_empty_runs=True,
            supports_geo_hint=True,
            # All v55 connectors are public-only. A restricted platform is
            # observed for a policy status but never uses an account.
            requires_login=False,
        ))

    # Each requested official careers site is intentionally exposed as a
    # separate source.  This preserves independent health/quarantine state and
    # makes a zero-job result traceable to the actual employer or job board.
    for official in OFFICIAL_SOURCES:
        is_egypt_priority = (
            config.ENABLE_EGYPT_PRIORITY_SOURCES
            and official.key in config.EGYPT_PRIORITY_SOURCE_KEYS
        )
        # Egyptian priority sources get a dedicated execution budget so the
        # official endpoint attempt and a genuinely JS-only Playwright render
        # are never killed by the generic 40s cap. Non-LinkedIn sources still
        # keep one shared, source-deadline-isolated ceiling — the priority
        # budget only makes that ceiling larger for the priority set.
        if is_egypt_priority:
            timeout = max(
                config.EGYPT_PRIORITY_SOURCE_TIMEOUT_SECONDS,
                config.PLAYWRIGHT_SOURCE_TIMEOUT_SECONDS,
            )
            # Priority sources earn a better queue position than the generic
            # official default (20) without ever beating LinkedIn (10). A
            # higher rank means the orchestrator keeps them alive under the
            # global phase deadline before lower-priority connectors.
            priority = min(config.source_priority(official.key, 999), 18)
        else:
            timeout = (
                config.PLAYWRIGHT_SOURCE_TIMEOUT_SECONDS
                if official.browser_fallback else config.CAREERS_API_SOURCE_TIMEOUT_SECONDS
            )
            priority = config.source_priority(official.key, 20)
        specs.append(SourceSpec(
            official.key,
            official.name,
            official_fetcher_for(official.key),
            priority,
            official.lane,
            "gold",
            allow_empty_runs=True,
            supports_geo_hint=True,
            requires_login=False,
            source_timeout_seconds=timeout,
        ))

    # ── OPTIONAL AKM sources — added only if installed ───────────────────────
    if fetch_gulf_boards is not None:
        specs.append(SourceSpec(
            "gulf_boards", "AKM Monster Gulf RSS",
            fetch_gulf_boards, 44, "gulf", "bronze",
            allow_empty_runs=True,
            enabled=getattr(config, "ENABLE_SOURCE_GULF_BOARDS", False),
        ))

    if fetch_jsearch_linkedin is not None:
        specs.append(SourceSpec(
            "linkedin_api", "AKM JSearch LinkedIn API",
            fetch_jsearch_linkedin, 66, "api", "silver",
            recency_required=True, allow_empty_runs=True,
            api_key_optional=True, supports_geo_hint=True,
            source_timeout_seconds=config.CAREERS_API_SOURCE_TIMEOUT_SECONDS,
            enabled=getattr(config, "ENABLE_SOURCE_LINKEDIN_API", False),
        ))

    return specs


def get_source_specs() -> list[SourceSpec]:
    """Return all enabled SourceSpec objects sorted by priority."""
    specs = _build_specs()

    filtered = []
    for spec in specs:
        if not spec.enabled:
            continue
        if spec.api_key_optional and not config.ALLOW_API_KEY_SOURCES:
            continue
        filtered.append(spec)

    return sorted(filtered, key=lambda s: s.priority)
