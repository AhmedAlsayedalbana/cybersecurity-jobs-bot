"""
Source registry — maps source names to their fetch functions.
Sources ordered by PRIORITY: Egypt/Gulf first → Cybersec-specific → Remote boards → API-based

Active sources:
  💼 LinkedIn: Egypt (all governorates) + Gulf (full) + Remote searches (ENABLED)
  🔒 Cybersecurity-specific: CyberSec Boards, Tech Boards
  🌍 Remote boards:          Remotive, Himalayas, Jobicy, RemoteOK,
                              Arbeitnow, WWR, Working Nomads
  🔑 API-based (optional):   Adzuna, Jooble, Findwork, Reed
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
# Order: LinkedIn Egypt/Gulf first → cybersec-specific → stable remote → API-based
ALL_FETCHERS = [
    # ── LinkedIn — Egypt & Gulf targeted (TOP PRIORITY SOURCE) ──
    ("LinkedIn",         fetch_linkedin),          # 🇪🇬🌙 Egypt all govs + Gulf + Remote

    # ── Cybersecurity-specific boards ──
    ("CyberSec Boards",  fetch_cybersec_boards),   # InfoSec-Jobs, ISACA, ISC2, etc.
    ("Tech Boards",      fetch_tech_boards),        # Dice, HackerOne, Bugcrowd

    # ── Reliable remote job boards ──
    ("Remotive",         fetch_remotive),
    ("Himalayas",        fetch_himalayas),
    ("Jobicy",           fetch_jobicy),
    ("RemoteOK",         fetch_remoteok),
    ("Arbeitnow",        fetch_arbeitnow),
    ("WWR",              fetch_wwr),
    ("Working Nomads",   fetch_workingnomads),

    # ── API-based (optional — need keys in secrets) ──
    ("Adzuna",           fetch_adzuna),
    ("Jooble",           fetch_jooble),
    ("Findwork",         fetch_findwork),
    ("Reed",             fetch_reed),
    # ("JSearch",          fetch_jsearch),  # Optional — RapidAPI key needed
]
