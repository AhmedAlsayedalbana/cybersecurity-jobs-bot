"""
Source registry — maps source names to their fetch functions.
Sources are ordered by reliability and relevance.

Active sources:
  🔒 Cybersecurity-specific: CyberSec Boards, Tech Boards
  🌍 Remote boards:          Remotive, Himalayas, Jobicy, RemoteOK,
                              Arbeitnow, WWR, Working Nomads
  🔑 API-based (optional):   JSearch (RapidAPI), Adzuna, Jooble, Findwork, Reed
  💼 LinkedIn scraping:      fetch_linkedin (may be rate-limited)

Disabled:
  ✗ USAJobs — US government only, not relevant for Egypt/Remote community
  ✗ The Muse — needs API key, low cybersec coverage
"""

from sources.cybersec_boards import fetch_cybersec_boards
from sources.tech_boards import fetch_tech_boards
from sources.remotive import fetch_remotive
from sources.himalayas import fetch_himalayas
from sources.jobicy import fetch_jobicy
from sources.remoteok import fetch_remoteok
from sources.arbeitnow import fetch_arbeitnow
from sources.wwr import fetch_wwr
from sources.workingnomads import fetch_workingnomads
from sources.linkedin import fetch_linkedin
from sources.adzuna import fetch_adzuna
from sources.findwork import fetch_findwork
from sources.jooble import fetch_jooble
from sources.reed import fetch_reed
from sources.jsearch import fetch_jsearch

# (display_name, fetch_function)
# Order: cybersec-specific first → stable remote boards → API-based
ALL_FETCHERS = [
    # ── Cybersecurity-specific boards (highest quality) ──
    ("CyberSec Boards",  fetch_cybersec_boards),   # InfoSec-Jobs, ISACA, ISC2, etc.
    ("Tech Boards",      fetch_tech_boards),        # Dice, HackerOne, Bugcrowd, Greenhouse

    # ── Reliable remote job boards ──
    ("Remotive",         fetch_remotive),
    ("Himalayas",        fetch_himalayas),
    ("Jobicy",           fetch_jobicy),
    ("RemoteOK",         fetch_remoteok),
    ("Arbeitnow",        fetch_arbeitnow),
    ("WWR",              fetch_wwr),
    ("Working Nomads",   fetch_workingnomads),

    # ── LinkedIn (Egypt + Remote searches) ──
    # ("LinkedIn",         fetch_linkedin),  # Disabled to reduce noise

    # ── API-based (optional — need keys in secrets) ──
    ("Adzuna",           fetch_adzuna),
    ("Findwork",         fetch_findwork),
    ("Jooble",           fetch_jooble),
    ("Reed",             fetch_reed),
    # ("JSearch",          fetch_jsearch),  # Disabled to reduce noise

    # ── Freelance (Upwork, Mustaqil, etc.) ──
    # ("Freelance",        fetch_freelance),  # Disabled (no fetcher implemented)
]
