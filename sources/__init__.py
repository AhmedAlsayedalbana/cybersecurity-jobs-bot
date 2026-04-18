"""
Source registry — v27

STATUS (from logs 2026-04-18):
  ✅ Gov Egypt          : ~9 jobs
  ✅ Egypt Alt          : ~23 jobs
  ✅ Egypt Companies    : ~1 job
  ✅ Gov Gulf           : ~44 jobs
  ✅ Gulf Expanded      : ~9 jobs
  ✅ CyberSec Boards    : ~4 jobs (Bugcrowd only)
  ✅ LinkedIn           : ~12 jobs (rate-limited)
  ✅ LinkedIn #Hiring   : v27 fix — uses correct session with CSRF token
  ✅ Google Jobs        : ~10 jobs (SerpAPI)
  ✅ Tech Boards        : ~100+ jobs
  ✅ Remotive/RemoteOK/Arbeitnow/WWR/Working Nomads: all working
  ✅ New Sources v27    : Greenhouse 11co + HN + GitHub + Telegram + Nitter + Akhtaboot + Forasna
  ✅ Expanded Sources   : Greenhouse 40 co

DEAD / DISABLED (v27):
  ❌ Himalayas          : HTTP 403 always → stubbed (0 jobs, no warnings)
  ❌ Jobicy             : API broken, parse errors → stubbed
  ❌ Gulf Boards        : Monster Gulf 0 every run → kept (cheap/fast)
  ❌ Freelance          : 0 every run → kept (cheap/fast)
  ❌ Adzuna/Jooble/Findwork/Reed: need API keys
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
from sources.himalayas        import fetch_himalayas   # stub — 403 dead
from sources.jobicy           import fetch_jobicy      # stub — API broken
from sources.remoteok         import fetch_remoteok
from sources.arbeitnow        import fetch_arbeitnow
from sources.wwr              import fetch_wwr
from sources.workingnomads    import fetch_workingnomads
from sources.adzuna           import fetch_adzuna
from sources.findwork         import fetch_findwork
from sources.jooble           import fetch_jooble
from sources.reed             import fetch_reed
from sources.freelance        import fetch_freelance
from sources.new_sources      import fetch_new_sources
from sources.expanded_sources import fetch_expanded_sources

ALL_FETCHERS = [
    # ── 1. Egypt 🇪🇬 (highest priority) ──────────────────────
    ("Gov Egypt",            fetch_gov_egypt),
    ("Egypt Alt",            fetch_egypt_alt),
    ("Egypt Companies",      fetch_egypt_companies),

    # ── 2. Gulf 🌙 ────────────────────────────────────────────
    ("Gov Gulf",             fetch_gov_gulf),
    ("Gulf Expanded",        fetch_gulf_expanded),
    ("Gulf Boards",          fetch_gulf_boards),

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
    ("Himalayas",            fetch_himalayas),   # stub — 0 jobs, no warnings
    ("Jobicy",               fetch_jobicy),      # stub — 0 jobs, no warnings
    ("RemoteOK",             fetch_remoteok),
    ("Arbeitnow",            fetch_arbeitnow),
    ("WWR",                  fetch_wwr),
    ("Working Nomads",       fetch_workingnomads),

    # ── 8. API-keyed sources ──────────────────────────────────
    ("Adzuna",               fetch_adzuna),
    ("Jooble",               fetch_jooble),
    ("Findwork",             fetch_findwork),
    ("Reed",                 fetch_reed),

    # ── 9. Misc ───────────────────────────────────────────────
    ("Freelance",            fetch_freelance),

    # ── 10. New & Expanded Sources v27 ───────────────────────
    ("New Sources v27",      fetch_new_sources),
    ("Expanded Sources v27", fetch_expanded_sources),
]
