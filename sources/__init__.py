"""
Source registry — v26

CONFIRMED ACTIVE (from v25 logs):
  ✅ Gov Egypt          : ~9 jobs
  ✅ Egypt Alt (v26)    : expanded — private sector +18 co, gov sector, Tanta, more keywords
  ✅ Egypt Companies    : ~1 job
  ✅ Gov Gulf           : ~44 jobs
  ✅ Gulf Expanded      : ~7 jobs
  ✅ CyberSec Boards    : ~4 jobs (Bugcrowd only)
  ✅ LinkedIn           : ~100 jobs (rate-limited)
  ✅ LinkedIn #Hiring   : rewritten — direct job search, 15 targeted queries
  ✅ Google Jobs        : expanded to 20 searches (Arabic + Gulf cities)
  ✅ Tech Boards        : ~163 jobs
  ✅ Himalayas          : fixed (API URL changed) — uses v2 API + RSS fallback
  ✅ Jobicy/RemoteOK/Arbeitnow/WWR/Remotive/Working Nomads : all working
  ✅ New Sources v26    : Greenhouse 11 co, HN Hiring, GitHub, Telegram, Nitter, InfoSec-Jobs, CISA
  ✅ Expanded Sources v26: Greenhouse 40 co + HN Hiring

DEAD / DISABLED:
  ❌ Gulf Boards (Monster): 0 — kept (cheap, might recover)
  ❌ Freelance (Mostaql/Khamsat): 0 — kept (cheap)
  ❌ Adzuna/Jooble/Findwork/Reed: need API keys (skip silently)
  ❌ Himalayas /api/search: 403 → fixed with v2 endpoint
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
from sources.new_sources      import fetch_new_sources       # v26: dead slugs removed
from sources.expanded_sources import fetch_expanded_sources  # v26: dead slugs removed

ALL_FETCHERS = [
    # ── 1. Egypt 🇪🇬 ─────────────────────────────────────────
    ("Gov Egypt",            fetch_gov_egypt),       # LinkedIn Egypt gov companies
    ("Egypt Alt",            fetch_egypt_alt),        # +35 companies, gov sector, 9 cities
    ("Egypt Companies",      fetch_egypt_companies),  # Security companies + internships

    # ── 2. Gulf 🌙 ────────────────────────────────────────────
    ("Gov Gulf",             fetch_gov_gulf),         # STC + Etisalat + LinkedIn Gulf
    ("Gulf Expanded",        fetch_gulf_expanded),    # 40+ Gulf companies
    ("Gulf Boards",          fetch_gulf_boards),      # Monster Gulf (0 but cheap)

    # ── 3. Cybersec boards ────────────────────────────────────
    ("CyberSec Boards",      fetch_cybersec_boards),  # Bugcrowd only (HackerOne/BuiltIn dead)

    # ── 4. LinkedIn ───────────────────────────────────────────
    ("LinkedIn",             fetch_linkedin),
    ("LinkedIn #Hiring",     fetch_linkedin_hiring),  # v26: direct job search, 15 queries

    # ── 5. Google Jobs ────────────────────────────────────────
    ("Google Jobs",          fetch_google_jobs),      # v26: 20 searches incl. Arabic

    # ── 6. Tech boards ───────────────────────────────────────
    ("Tech Boards",          fetch_tech_boards),      # Greenhouse big tech

    # ── 7. Remote job boards ─────────────────────────────────
    ("Remotive",             fetch_remotive),
    ("Himalayas",            fetch_himalayas),        # v26: fixed API URL (was 403)
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

    # ── 9. Freelance ──────────────────────────────────────────
    ("Freelance",            fetch_freelance),

    # ── 10. New Sources v26 ───────────────────────────────────
    ("New Sources v26",      fetch_new_sources),      # Bayt HTML, GH Cybersec(11co), HN, GitHub, Telegram, Nitter, InfoSec-Jobs, CISA

    # ── 11. Expanded Sources v26 ─────────────────────────────
    ("Expanded Sources v26", fetch_expanded_sources), # Greenhouse 40 companies + HN Hiring
]
