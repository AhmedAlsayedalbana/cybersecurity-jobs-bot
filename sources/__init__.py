"""
Source registry — v25

Log analysis (2026-04-16) — dead sources marked, clean registry:

ACTIVE (confirmed producing jobs):
  ✅ Gov Egypt          : 9 jobs
  ✅ Egypt Alt          : 58 jobs
  ✅ Egypt Companies    : 1 job   (DrJobPro+Akhtaboot dead, only internships working)
  ✅ Gov Gulf           : 46 jobs
  ✅ Gulf Expanded      : 7 jobs  (NaukriGulf timeout removed)
  ✅ CyberSec Boards    : 4 jobs  (Bugcrowd only; CyberSecJobs/HackerOne/BuiltIn dead)
  ✅ LinkedIn           : ~100 jobs (rate-limited but works)
  ✅ LinkedIn #Hiring   : 12 jobs
  ✅ Google Jobs        : 10 jobs
  ✅ Tech Boards        : 163 jobs
  ✅ Remotive           : active
  ✅ Himalayas          : 280 jobs
  ✅ Jobicy             : 100 jobs
  ✅ RemoteOK           : 96 jobs
  ✅ Arbeitnow          : 100 jobs
  ✅ WWR               : 120 jobs
  ✅ Working Nomads     : 19 jobs
  ✅ New Sources v25    : Bayt HTML, GH Cybersec, Reddit RSS, HN, GitHub, Telegram, Nitter, InfoSec-Jobs, CISA
  ✅ Expanded v25       : Greenhouse 40 companies + HN Hiring

SKIPPED (key not set):
  ⚠️ Adzuna, Jooble, Findwork, Reed — need API keys

DEAD (confirmed from logs, removed from new_sources + expanded):
  ❌ Gulf Boards (Monster): 0 jobs — kept in list (cheap call)
  ❌ Freelance (Mostaql/Khamsat/Truelancer): 0 jobs — kept (cheap)
  ❌ Lever API: all 404 — fully removed from expanded_sources
  ❌ YC workatastartup, Sequoia, 500Global: 404/0 — removed
  ❌ Jobspresso, Outsourcely (DNS dead), Nodesk, Reddit JSON, SO Jobs: removed
  ❌ CyberSeek, Akhtaboot, NaukriGulf (timeout): removed
  ❌ GulfTalent, Wuzzuf expanded, LinkedIn Egypt expanded: 0 — removed
"""

from sources.gov_egypt        import fetch_gov_egypt
from sources.egypt_alt        import fetch_egypt_alt
from sources.egypt_companies  import fetch_egypt_companies
from sources.gov_gulf         import fetch_gov_gulf
from sources.gulf_expanded    import fetch_gulf_expanded
from sources.gulf_boards      import fetch_gulf_boards
from sources.cybersec_boards  import fetch_cybersec_boards
from sources.linkedin         import fetch_linkedin
from sources.linkedin_hiring  import fetch_linkedin_hiring
from sources.google_jobs      import fetch_google_jobs
from sources.tech_boards      import fetch_tech_boards
from sources.remotive         import fetch_remotive
from sources.himalayas        import fetch_himalayas
from sources.jobicy           import fetch_jobicy
from sources.remoteok         import fetch_remoteok
from sources.arbeitnow        import fetch_arbeitnow
from sources.wwr              import fetch_wwr
from sources.workingnomads    import fetch_workingnomads
from sources.adzuna           import fetch_adzuna
from sources.findwork         import fetch_findwork
from sources.jooble           import fetch_jooble
from sources.reed             import fetch_reed
from sources.freelance        import fetch_freelance
from sources.jsearch          import fetch_jsearch
from sources.new_sources      import fetch_new_sources       # v25: fixed, import time added
from sources.expanded_sources import fetch_expanded_sources  # v25: dead sources removed

ALL_FETCHERS = [
    # ── 1. Egypt 🇪🇬 ─────────────────────────────────────────
    ("Gov Egypt",            fetch_gov_egypt),
    ("Egypt Alt",            fetch_egypt_alt),
    ("Egypt Companies",      fetch_egypt_companies),

    # ── 2. Gulf 🌙 ────────────────────────────────────────────
    ("Gov Gulf",             fetch_gov_gulf),
    ("Gulf Expanded",        fetch_gulf_expanded),
    # ("Gulf Boards",        fetch_gulf_boards),  # Monster Gulf: always 0 — disabled

    # ── 3. Cybersec boards ────────────────────────────────────
    ("CyberSec Boards",      fetch_cybersec_boards),

    # ── 4. LinkedIn ───────────────────────────────────────────
    ("LinkedIn",             fetch_linkedin),
    ("LinkedIn #Hiring",     fetch_linkedin_hiring),

    # ── 5. Google Jobs ────────────────────────────────────────
    ("Google Jobs",          fetch_google_jobs),

    # ── 6. Tech boards ───────────────────────────────────────
    ("Tech Boards",          fetch_tech_boards),

    # ── 7. Remote job boards ─────────────────────────────────
    ("Remotive",             fetch_remotive),
    ("Himalayas",            fetch_himalayas),
    ("Jobicy",               fetch_jobicy),
    ("RemoteOK",             fetch_remoteok),
    ("Arbeitnow",            fetch_arbeitnow),
    ("WWR",                  fetch_wwr),
    ("Working Nomads",       fetch_workingnomads),

    # ── 8. API-based (need keys) ──────────────────────────────
    ("Adzuna",               fetch_adzuna),
    ("Jooble",               fetch_jooble),
    ("Findwork",             fetch_findwork),
    ("Reed",                 fetch_reed),
    # ("JSearch",            fetch_jsearch),  # Uncomment if RAPIDAPI_KEY set

    # ── 9. Freelance — disabled (Mostaql/Khamsat/Truelancer all return 0)
    # ("Freelance",          fetch_freelance),

    # ── 10. New Sources v25 ───────────────────────────────────
    ("New Sources v25",      fetch_new_sources),

    # ── 11. Expanded Sources v25 ─────────────────────────────
    ("Expanded Sources v25", fetch_expanded_sources),
]
