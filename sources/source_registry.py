"""
sources/source_registry.py — v47

Priority order (LinkedIn first → Wuzzuf → Freelance → rest):
  10  LinkedIn Unified  (Egypt + Gulf + Remote, all queries)
  15  Wuzzuf            (Egypt #1 direct)
  20  Mostaql           (Arabic freelance)
  21  Freelancer        (Global freelance RSS)
  22  Khamsat           (Arabic freelance, if enabled)
  30  Greenhouse Cybersec (vendor direct APIs)
  35  Greenhouse Expanded (Big Tech + SaaS)
  38  Cybersec Boards   (Bugcrowd etc.)
  40  Akhtaboot / DrJobPro / MENA Boards  (Egypt+Gulf direct)
  43  Jina Scraper      (Bayt + NaukriGulf + GulfTalent + Akhtaboot via Jina)
  50  Telegram Channels
  51  Reddit / GitHub Hiring
  65  JSearch Enhanced  (RapidAPI — optional)

DISABLED (dead):
  ✗ linkedin_extended  (missing _linkedin_search_jobs — queries merged into linkedin_unified)
  ✗ google_intel       (SerpAPI 429 on every request — Wuzzuf direct kept inside google_jobs)
  ✗ gulf_monster       (0 jobs on every run — feed likely changed)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
import config
from sources.cybersec_boards import fetch_cybersec_boards
from sources.greenhouse_expanded import fetch_greenhouse_expanded
from sources.jina_scraper import fetch_jina_boards
from sources.jsearch_enhanced import fetch_jsearch_enhanced
from sources.linkedin_unified import fetch_linkedin_unified_async
from sources.mena_boards import fetch_mena_boards
from sources.new_sources import _fetch_greenhouse_cybersec
from sources.priority_sources import (
    fetch_fiverr_public, fetch_freelancer_priority,
    fetch_google_intelligence, fetch_khamsat_priority,
    fetch_mostaql_priority, fetch_reddit_discord,
    fetch_telegram_channels, fetch_upwork_public,
    fetch_wuzzuf_priority,
)

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
    unstable: bool = False
    requires_login: bool = False
    api_key_optional: bool = False
    enabled: bool = True
    supports_geo_hint: bool = False
    rate_limited: bool = False

def _build_specs() -> list[SourceSpec]:
    return [
        # ── TIER 1: LinkedIn (Priority #1) ──────────────────────────────
        SourceSpec("linkedin_unified", "LinkedIn Unified",
            fetch_linkedin_unified_async, 10, "core", "gold",
            recency_required=True),

        # ── TIER 2: Wuzzuf (Priority #2 — Egypt's top board) ────────────
        SourceSpec("wuzzuf", "Wuzzuf",
            fetch_wuzzuf_priority, 15, "core", "gold",
            recency_required=True),

        # ── TIER 3: Freelance (Priority #3) ─────────────────────────────
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

        # ── TIER 4: Greenhouse / Cybersec vendor boards ──────────────────
        SourceSpec("greenhouse_cybersec", "Greenhouse Cybersec",
            _fetch_greenhouse_cybersec, 30, "core", "gold",
            recency_required=True, allow_empty_runs=True),
        SourceSpec("greenhouse_expanded", "Greenhouse Expanded (Big Tech + SaaS)",
            fetch_greenhouse_expanded, 35, "core", "silver",
            allow_empty_runs=True,
            enabled=getattr(config, "ENABLE_SOURCE_GREENHOUSE_EXPANDED", True)),
        SourceSpec("cybersec_boards", "Cybersec Boards",
            fetch_cybersec_boards, 38, "core", "silver",
            recency_required=True, allow_empty_runs=True),

        # ── TIER 5: MENA Boards (Egypt + Gulf — direct HTTP) ─────────────
        SourceSpec("mena_boards", "MENA Boards (Akhtaboot+DrJobPro+Forasna+Tanqeeb)",
            fetch_mena_boards, 40, "gulf", "silver",
            allow_empty_runs=True, supports_geo_hint=True,
            enabled=getattr(config, "ENABLE_SOURCE_MENA_BOARDS", True)),

        # ── TIER 6: Jina Scraper (Bayt+NaukriGulf+GulfTalent+Akhtaboot) ─
        SourceSpec("jina_boards", "Jina Scraper (Bayt+NaukriGulf+GulfTalent+MENA)",
            fetch_jina_boards, 43, "gulf", "bronze",
            allow_empty_runs=True, supports_geo_hint=True,
            enabled=getattr(config, "ENABLE_JINA_SCRAPER", True)),

        # ── TIER 7: Community ────────────────────────────────────────────
        SourceSpec("telegram_channels", "Telegram Channels",
            fetch_telegram_channels, 50, "community", "silver",
            recency_required=True, allow_empty_runs=True),
        SourceSpec("reddit_discord", "Reddit / Discord",
            fetch_reddit_discord, 51, "community", "bronze",
            recency_required=True, allow_empty_runs=True),

        # ── TIER 8: RapidAPI (optional, needs RAPIDAPI_KEY) ──────────────
        SourceSpec("jsearch_enhanced", "JSearch Enhanced (LinkedIn+Indeed via RapidAPI)",
            fetch_jsearch_enhanced, 65, "api", "silver",
            recency_required=True, allow_empty_runs=True, api_key_optional=True,
            supports_geo_hint=True,
            enabled=getattr(config, "ENABLE_SOURCE_JSEARCH_ENHANCED", True)),

        # ── TIER 9: Unstable (disabled by default) ───────────────────────
        SourceSpec("upwork", "Upwork",
            fetch_upwork_public, 84, "freelance", "bronze",
            unstable=True, enabled=config.ENABLE_UNSTABLE_SOURCES),
        SourceSpec("fiverr", "Fiverr",
            fetch_fiverr_public, 85, "freelance", "bronze",
            unstable=True, enabled=config.ENABLE_UNSTABLE_SOURCES),
    ]

def get_source_specs() -> list[SourceSpec]:
    specs = _build_specs()
    out: list[SourceSpec] = []
    for spec in specs:
        if not spec.enabled:
            continue
        if spec.unstable and not config.ENABLE_UNSTABLE_SOURCES:
            continue
        if spec.requires_login:
            continue
        out.append(spec)
    out.sort(key=lambda s: s.priority)
    return out
