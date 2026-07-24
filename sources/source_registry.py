"""
sources/source_registry.py — Ultimate v50+

Merged source registry: MCO's comprehensive coverage + MCL's tier-based
priority architecture + dead-source documentation.

Priority order (highest → lowest):
  10  LinkedIn Unified      (Egypt + Gulf + Remote, all queries)
  15  Wuzzuf                (Egypt #1 direct board)
  20  Mostaql               (Arabic freelance platform)
  21  Freelancer            (Global freelance RSS)
  22  Khamsat               (Arabic freelance — optional)
  30  Greenhouse Cybersec   (vendor direct APIs)
  35  Greenhouse Expanded   (Big Tech + SaaS)
  36  Expanded Sources      (AKM aggregator bundle)
  37  Tech Boards           (AKM tech-specific boards)
  38  Cybersec Boards       (Bugcrowd, HackerOne listings)
  40  MENA Boards           (disabled placeholder; legacy dead boards skipped)
  43  Jina Scraper          (Bayt + NaukriGulf + GulfTalent)
  44  Gulf Boards           (AKM Monster Gulf RSS — optional)
  50  Telegram Channels
  51  Reddit / GitHub Hiring
  65  JSearch Enhanced      (LinkedIn+Indeed via RapidAPI — optional)
  66  LinkedIn API          (AKM JSearch LinkedIn — optional)
  84  Upwork                (unstable — disabled by default)
  85  Fiverr                (unstable — disabled by default)
  90  Google Intelligence   (SerpAPI — unstable, disabled by default)

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
from sources.marketplace_sources import PUBLIC_SPECS, fetcher_for
from sources.official_careers import OFFICIAL_SOURCES, fetcher_for as official_fetcher_for
from sources.public_remote_feeds import (
    fetch_arbeitnow_security,
    fetch_remotive_security,
    fetch_remoteok_security,
    fetch_wwr_security,
)
from sources.priority_sources import (
    fetch_google_intelligence,
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


def _build_specs() -> list[SourceSpec]:
    specs = [
        # ── TIER 1: LinkedIn (Priority #1) ──────────────────────────────────
        SourceSpec("linkedin_unified", "LinkedIn Unified",
            fetch_linkedin_unified_async, 10, "core", "gold",
            recency_required=True),

        SourceSpec("egytech_fyi", "EgyTech.fyi",
            fetch_careers_egypt, 18, "egypt", "silver",
            recency_required=True, allow_empty_runs=True, supports_geo_hint=True),
        # ── TIER 4: Greenhouse / Cybersec Vendor Boards ──────────────────────
        SourceSpec("greenhouse_cybersec", "Greenhouse Cybersec",
            _fetch_greenhouse_cybersec, 30, "core", "gold",
            recency_required=True, allow_empty_runs=True),
        SourceSpec("greenhouse_expanded", "Greenhouse Expanded (Big Tech + SaaS)",
            fetch_greenhouse_expanded, 35, "core", "silver",
            recency_required=True, allow_empty_runs=True,
            enabled=getattr(config, "ENABLE_SOURCE_GREENHOUSE_EXPANDED", True)),

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

        # These sources are public API/RSS feeds, not browser-rendered
        # marketplace pages.  Each result has a canonical application URL and
        # source-provided publication date, so it passes strict publishing.
        SourceSpec("remotive_security", "Remotive Security API",
            fetch_remotive_security, 27, "freelance", "silver",
            recency_required=True, allow_empty_runs=True, supports_geo_hint=True,
            enabled=getattr(config, "ENABLE_SOURCE_REMOTIVE_SECURITY", True)),
        SourceSpec("remoteok_security", "RemoteOK Security API",
            fetch_remoteok_security, 28, "freelance", "silver",
            recency_required=True, allow_empty_runs=True, supports_geo_hint=True,
            enabled=getattr(config, "ENABLE_SOURCE_REMOTEOK_SECURITY", True)),
        SourceSpec("wwr_security", "We Work Remotely Security RSS",
            fetch_wwr_security, 29, "freelance", "silver",
            recency_required=True, allow_empty_runs=True, supports_geo_hint=True,
            enabled=getattr(config, "ENABLE_SOURCE_WWR_SECURITY", True)),
        SourceSpec("arbeitnow_security", "Arbeitnow Security API",
            fetch_arbeitnow_security, 30, "freelance", "silver",
            recency_required=True, allow_empty_runs=True, supports_geo_hint=True,
            enabled=getattr(config, "ENABLE_SOURCE_ARBEITNOW_SECURITY", True)),

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
            enabled=(
                getattr(config, "ENABLE_SOURCE_JSEARCH_ENHANCED", True)
                and bool(getattr(config, "RAPIDAPI_KEY", ""))
            )),

        SourceSpec("google_intel", "Google Search Intelligence",
            fetch_google_intelligence, 90, "api", "bronze",
            recency_required=True, allow_empty_runs=True, api_key_optional=True,
            enabled=config.ENABLE_UNSTABLE_SOURCES),
    ]

    # Browser-rendered marketplace pages can require a signed session or
    # deploy a WAF.  Wuzzuf remains enabled, while the rest are an explicit
    # diagnostic opt-in so failed HTML pages do not appear as production zeros.
    for market in PUBLIC_SPECS:
        enabled = (
            market.key == "wuzzuf"
            or getattr(config, "ENABLE_LEGACY_MARKETPLACE_SOURCES", False)
        )
        specs.append(SourceSpec(
            market.key,
            market.name,
            fetcher_for(market.key),
            market.priority,
            "freelance" if market.content_type == "client_project" else ("egypt" if market.geo_hint == "egypt" else "gulf"),
            "silver",
            recency_required=True,
            allow_empty_runs=True,
            supports_geo_hint=True,
            requires_login=False,
            enabled=enabled,
        ))

    # Each requested official careers site is intentionally exposed as a
    # separate source.  This preserves independent health/quarantine state and
    # makes a zero-job result traceable to the actual employer or job board.
    for official in OFFICIAL_SOURCES:
        specs.append(SourceSpec(
            official.key,
            official.name,
            official_fetcher_for(official.key),
            24 if official.lane == "egypt" else 32,
            official.lane,
            "gold",
            allow_empty_runs=True,
            supports_geo_hint=True,
            requires_login=False,
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
