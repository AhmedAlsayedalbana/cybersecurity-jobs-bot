"""
Source registry V9 — ordered by priority and reliability.

CHANGES vs V8:
  - gov_egypt:       FIXED ThreadPoolExecutor timeout crash
  - gov_gulf:        FIXED ThreadPoolExecutor timeout crash; removed dead sources
  - cybersec_boards: FIXED broken URLs (InfoSec-Jobs, ISACA, ISC2, SecurityJobs)
                     MOVED Greenhouse + Lever here (was in tech_boards)
                     ADDED Dice via official API (replaces dead Seibert proxy)
  - tech_boards:     Simplified to Dice only (deduplication removed)
  - freelance:       FIXED all dead RSS feeds (Upwork 410, Freelancer 404,
                     Khamsat 404, Mustaqil 404) → replaced with working scrapers
  - egypt_alt:       FIXED Forasna URL; ADDED CareerJet Egypt, Naukrigulf
  - google_jobs:     Unchanged (SerpAPI — works when key set)

REMOVED ENTIRELY (dead, waste time, 0 results every run):
  ❌ Bayt RSS         (403 Forbidden — use JSON-LD scraping in gov_gulf instead)
  ❌ Seibert Dice proxy (DNS failure — replaced with official Dice API)
  ❌ ISC2 old URL     (fixed in cybersec_boards)
  ❌ ISACA old URL    (fixed in cybersec_boards)
"""

from sources.gov_egypt       import fetch_gov_egypt
from sources.gov_gulf        import fetch_gov_gulf
from sources.cybersec_boards import fetch_cybersec_boards
from sources.egypt_alt       import fetch_egypt_alt
from sources.linkedin        import fetch_linkedin
from sources.google_jobs     import fetch_google_jobs
from sources.tech_boards     import fetch_tech_boards
from sources.remotive        import fetch_remotive
from sources.himalayas       import fetch_himalayas
from sources.jobicy          import fetch_jobicy
from sources.remoteok        import fetch_remoteok
from sources.arbeitnow       import fetch_arbeitnow
from sources.wwr             import fetch_wwr
from sources.workingnomads   import fetch_workingnomads
from sources.adzuna          import fetch_adzuna
from sources.findwork        import fetch_findwork
from sources.jooble          import fetch_jooble
from sources.reed            import fetch_reed
from sources.freelance       import fetch_freelance
from sources.jsearch         import fetch_jsearch

ALL_FETCHERS = [
    # ── 1. Egypt — top priority ──────────────────────────────
    ("Gov Egypt",       fetch_gov_egypt),      # Wuzzuf RSS + company pages + CBE + Indeed
    ("Egypt Alt",       fetch_egypt_alt),       # CareerJet + Forasna + Naukrigulf + LinkedIn search

    # ── 2. Gulf ──────────────────────────────────────────────
    ("Gov Gulf",        fetch_gov_gulf),        # STC, Omantel, TDRA, Etisalat, Bayt, Indeed Gulf

    # ── 3. Cybersec-specific boards ──────────────────────────
    ("CyberSec Boards", fetch_cybersec_boards), # CyberSecJobs, InfoSec-Jobs(fixed), ISACA(fixed),
                                                # Dice, HackerOne, Bugcrowd, Greenhouse, Lever

    # ── 4. LinkedIn ──────────────────────────────────────────
    ("LinkedIn",        fetch_linkedin),        # Egypt + Gulf + Remote

    # ── 5. Google Jobs (SerpAPI — optional key) ──────────────
    ("Google Jobs",     fetch_google_jobs),

    # ── 6. Dice via tech_boards ───────────────────────────────
    ("Tech Boards",     fetch_tech_boards),

    # ── 7. Remote job boards ─────────────────────────────────
    ("Remotive",        fetch_remotive),
    ("Himalayas",       fetch_himalayas),
    ("Jobicy",          fetch_jobicy),
    ("RemoteOK",        fetch_remoteok),
    ("Arbeitnow",       fetch_arbeitnow),
    ("WWR",             fetch_wwr),
    ("Working Nomads",  fetch_workingnomads),

    # ── 8. API-based (optional — need keys) ──────────────────
    ("Adzuna",          fetch_adzuna),
    ("Jooble",          fetch_jooble),
    ("Findwork",        fetch_findwork),
    ("Reed",            fetch_reed),
    # ("JSearch",        fetch_jsearch),   # Uncomment if RAPIDAPI_KEY is set

    # ── 9. Freelance ─────────────────────────────────────────
    ("Freelance",       fetch_freelance),       # Upwork(fixed), PPH, Mostaql(fixed), Khamsat(fixed)
]
