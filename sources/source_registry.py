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
from sources.cybersec_boards import fetch_cybersec_boards
from sources.egypt_direct import fetch_bayt_egypt, fetch_careers_egypt, fetch_wuzzuf_rss
from sources.expanded_sources import fetch_expanded_sources
from sources.greenhouse_expanded import fetch_greenhouse_expanded
from sources.gulf_direct import fetch_gulftalent_api, fetch_jobzella_gulf, fetch_naukrigulf_search
from sources.jina_scraper import fetch_jina_boards
from sources.jsearch_enhanced import fetch_jsearch_enhanced
from sources.linkedin_unified import fetch_linkedin_unified_async
from sources.mena_boards import fetch_mena_boards
from sources.new_sources import _fetch_greenhouse_cybersec
from sources.tech_boards import fetch_tech_boards
from sources.priority_sources import (
    fetch_fiverr_public,
    fetch_freelancer_priority,
    fetch_google_intelligence,
    fetch_khamsat_priority,
    fetch_mostaql_priority,
    fetch_reddit_discord,
    fetch_telegram_channels,
    fetch_upwork_public,
    fetch_wuzzuf_priority,
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

        # ── TIER 2: Wuzzuf (Priority #2 — Egypt's top board) ────────────────
        SourceSpec("wuzzuf", "Wuzzuf",
            fetch_wuzzuf_priority, 15, "core", "gold",
            recency_required=True),
        SourceSpec("wuzzuf_rss", "Wuzzuf RSS",
            fetch_wuzzuf_rss, 16, "egypt", "gold",
            recency_required=True, allow_empty_runs=True, supports_geo_hint=True),
        SourceSpec("bayt_egypt", "Bayt Egypt",
            fetch_bayt_egypt, 17, "egypt", "gold",
            recency_required=True, allow_empty_runs=True, supports_geo_hint=True),
        SourceSpec("egytech_fyi", "EgyTech.fyi",
            fetch_careers_egypt, 18, "egypt", "silver",
            recency_required=True, allow_empty_runs=True, supports_geo_hint=True),

        # ── TIER 3: Freelance Platforms ──────────────────────────────────────
        SourceSpec("mostaql", "Mostaql",
            fetch_mostaql_priority, 20, "freelance", "silver",
            recency_required=True, allow_empty_runs=True),
        SourceSpec("freelancer", "Freelancer",
            fetch_freelancer_priority, 21, "freelance", "bronze",
            recency_required=True, allow_empty_runs=True),
        SourceSpec("khamsat", "Khamsat",
            fetch_khamsat_priority, 22, "freelance", "bronze",
            recency_required=True, allow_empty_runs=True,
            enabled=config.ENABLE_UNSTABLE_SOURCES),

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
        SourceSpec("cybersec_boards", "Cybersec Boards (Bugcrowd etc.)",
            fetch_cybersec_boards, 38, "core", "silver",
            recency_required=True, allow_empty_runs=True),

        # ── TIER 5: MENA Boards (Egypt + Gulf — direct HTTP) ─────────────────
        SourceSpec("mena_boards", "MENA Boards (legacy dead boards skipped)",
            fetch_mena_boards, 40, "gulf", "silver",
            allow_empty_runs=True, supports_geo_hint=True,
            enabled=getattr(config, "ENABLE_SOURCE_MENA_BOARDS", True)),

        SourceSpec("gulftalent", "GulfTalent Direct",
            fetch_gulftalent_api, 45, "gulf", "silver",
            recency_required=True, allow_empty_runs=True, supports_geo_hint=True),
        SourceSpec("naukrigulf", "NaukriGulf Direct",
            fetch_naukrigulf_search, 46, "gulf", "silver",
            recency_required=True, allow_empty_runs=True, supports_geo_hint=True),
        SourceSpec("jobzella", "Jobzella Gulf",
            fetch_jobzella_gulf, 47, "gulf", "silver",
            recency_required=True, allow_empty_runs=True, supports_geo_hint=True),

        # ── TIER 6: Jina Scraper ──────────────────────────────────────────────
        SourceSpec("jina_boards", "Jina Scraper (Bayt+NaukriGulf+GulfTalent+MENA)",
            fetch_jina_boards, 43, "gulf", "bronze",
            allow_empty_runs=True, supports_geo_hint=True,
            enabled=getattr(config, "ENABLE_JINA_SCRAPER", True)),

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
            enabled=getattr(config, "ENABLE_SOURCE_JSEARCH_ENHANCED", True)),

        # ── TIER 9: Unstable (disabled by default) ───────────────────────────
        SourceSpec("upwork", "Upwork",
            fetch_upwork_public, 84, "freelance", "bronze",
            unstable=True, enabled=config.ENABLE_UNSTABLE_SOURCES),
        SourceSpec("fiverr", "Fiverr",
            fetch_fiverr_public, 85, "freelance", "bronze",
            unstable=True, enabled=config.ENABLE_UNSTABLE_SOURCES),
        SourceSpec("google_intel", "Google Search Intelligence",
            fetch_google_intelligence, 90, "api", "bronze",
            recency_required=True, allow_empty_runs=True, api_key_optional=True,
            enabled=config.ENABLE_UNSTABLE_SOURCES),
    ]

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
