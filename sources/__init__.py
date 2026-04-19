"""
Source registry — v31

CHANGES vs v27:
  ✅ Arab Boards (NEW)        : Bayt RSS + Akhtaboot + Tanqeeb + DrJobPro
  ✅ LinkedIn Posts (NEW)     : HR-style "#hiring" post search + Google cache
  ✅ Google Jobs (FIXED)      : Removed duplicate code + added Wuzzuf/Forasna direct
  ✅ Egypt Companies (UPDATED): +30 more companies, multi-keyword search, shared session
  🗑️  Gulf Boards             : Monster Gulf 0 every run → REMOVED
  🗑️  Freelance               : 0 every run → REMOVED
  🗑️  Himalayas               : HTTP 403 dead → REMOVED (was already stub)
  🗑️  Jobicy                  : API broken → REMOVED (was already stub)
  🗑️  Adzuna/Jooble/Findwork/Reed: need API keys → kept but silently skip if no key

STATUS (from logs 2026-04-19):
  ✅ Gov Egypt          : ~29 jobs
  ✅ Egypt Alt          : ~39 jobs
  ✅ Egypt Companies    : ~1+ jobs (improved with shared session + multi-kw)
  ✅ Gov Gulf           : ~46 jobs
  ✅ Gulf Expanded      : ~9 jobs
  ✅ CyberSec Boards    : ~6 jobs
  ✅ LinkedIn           : ~25 jobs (rate-limited but working)
  ✅ LinkedIn #Hiring   : working — shows company + job title from LinkedIn job pages
  ✅ LinkedIn Posts     : NEW — catches HR "we are hiring" search posts
  ✅ Google Jobs        : ~10 jobs (SerpAPI) + Wuzzuf/Forasna direct
  ✅ Arab Boards        : NEW — Bayt + Akhtaboot + Tanqeeb + DrJobPro
  ✅ Tech Boards        : ~249 jobs
  ✅ Remotive/RemoteOK/Arbeitnow/WWR/Working Nomads: all working
  ✅ New Sources v27    : ~222 jobs
  ✅ Expanded Sources   : ~393 jobs
"""

from sources.gov_egypt        import fetch_gov_egypt
from sources.egypt_alt        import fetch_egypt_alt
from sources.egypt_companies  import fetch_egypt_companies
from sources.gov_gulf         import fetch_gov_gulf
from sources.gulf_expanded    import fetch_gulf_expanded
from sources.cybersec_boards  import fetch_cybersec_boards
from sources.linkedin         import fetch_linkedin
from sources.linkedin_hiring  import fetch_linkedin_hiring
from sources.linkedin_posts   import fetch_linkedin_posts    # v31 NEW
from sources.arab_boards      import fetch_arab_boards       # v31 NEW
from sources.google_jobs      import fetch_google_jobs
from sources.tech_boards      import fetch_tech_boards
from sources.remotive         import fetch_remotive
from sources.remoteok         import fetch_remoteok
from sources.arbeitnow        import fetch_arbeitnow
from sources.wwr              import fetch_wwr
from sources.workingnomads    import fetch_workingnomads
from sources.adzuna           import fetch_adzuna
from sources.findwork         import fetch_findwork
from sources.jooble           import fetch_jooble
from sources.reed             import fetch_reed
from sources.new_sources      import fetch_new_sources
from sources.expanded_sources import fetch_expanded_sources

ALL_FETCHERS = [
    # ── 1. Egypt 🇪🇬 (highest priority) ──────────────────────
    ("Gov Egypt",            fetch_gov_egypt),       # LinkedIn Egypt gov + companies
    ("Egypt Alt",            fetch_egypt_alt),        # Wuzzuf + LinkedIn governorates
    ("Egypt Companies",      fetch_egypt_companies),  # 120+ Egyptian company pages

    # ── 2. Arab Boards (Egypt + Gulf) ────────────────────────
    # Arab Boards: all dead (Bayt 403, Tanqeeb 403, DrJobPro 404) — stub      # Bayt + Akhtaboot + Tanqeeb + DrJobPro

    # ── 3. Gulf 🌙 ────────────────────────────────────────────
    ("Gov Gulf",             fetch_gov_gulf),         # STC, TDRA, Etisalat + LinkedIn Gulf
    ("Gulf Expanded",        fetch_gulf_expanded),    # 40+ Gulf companies

    # ── 4. Cybersec-specific boards ──────────────────────────
    ("CyberSec Boards",      fetch_cybersec_boards),  # Bugcrowd + BuiltIn

    # ── 5. LinkedIn (global + #Hiring + HR posts) ────────────
    ("LinkedIn",             fetch_linkedin),
    ("LinkedIn #Hiring",     fetch_linkedin_hiring),  # Job listings tagged with hiring
    ("LinkedIn Posts",       fetch_linkedin_posts),   # HR-style "we are hiring" posts

    # ── 6. Google Jobs + Wuzzuf + Forasna ────────────────────
    ("Google Jobs",          fetch_google_jobs),      # SerpAPI + Wuzzuf + Forasna direct

    # ── 7. Tech boards ───────────────────────────────────────
    ("Tech Boards",          fetch_tech_boards),      # Big Tech Greenhouse

    # ── 8. Remote job boards ─────────────────────────────────
    ("Remotive",             fetch_remotive),
    ("RemoteOK",             fetch_remoteok),
    ("Arbeitnow",            fetch_arbeitnow),
    ("WWR",                  fetch_wwr),
    ("Working Nomads",       fetch_workingnomads),

    # ── 9. API-based (need keys — silently skip if unset) ─────
    ("Adzuna",               fetch_adzuna),
    ("Jooble",               fetch_jooble),
    ("Findwork",             fetch_findwork),
    ("Reed",                 fetch_reed),

    # ── 10. Creative v27 Sources ──────────────────────────────
    ("New Sources v27",      fetch_new_sources),      # Greenhouse cybersec, Telegram, GitHub, Nitter

    # ── 11. Expanded Sources v27 🚀 ──────────────────────────
    ("Expanded Sources v27", fetch_expanded_sources), # 50+ Greenhouse/Lever, YC, HN Hiring, MENA+
]
