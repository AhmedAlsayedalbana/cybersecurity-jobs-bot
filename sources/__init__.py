"""
Source registry — v23

PRIORITY ORDER:
  1. Egypt (🇪🇬) — All governorates, public + private sector + #Hiring posts
  2. Egypt expanded — Security companies, internships, DrJobPro, Akhtaboot
  3. Gulf (🌙) — KSA, UAE, Kuwait, Qatar, Bahrain, Oman + expanded companies
  4. Gulf expanded — Internships, Akhtaboot, Naukrigulf
  5. Cybersec boards (global)
  6. LinkedIn (global jobs + #Hiring posts) [v23: trimmed 107→52 searches + 8-min budget]
  7. Google Jobs (SerpAPI)
  8. Tech boards
  9. Remote job boards
  10. API-based (optional — need keys)
  11. Freelance (Arab + global)
  12. New Sources v17 — Greenhouse cybersec, Telegram, GitHub, Bug Bounty
  13. Expanded Sources v18 — Greenhouse/Lever 50+ companies, YC, HN Hiring, MENA+

DEAD SOURCES (removed after log analysis 2026-04-16):
  ❌ Bayt RSS         — HTTP 403
  ❌ Wellfound        — HTTP 403
  ❌ Dice RSS         — 0 results
  ❌ DrJobPro         — HTTP 404
  ❌ Laimoon          — HTTP 404
  ❌ Reddit r/netsec  — HTTP 403
  ❌ Jobzella         — HTTP 404
  ❌ NTI Egypt        — HTTP 404
  ❌ Wamda            — HTTP 404
  ❌ EgyTech.net      — SSL error
  ❌ HackerOne jobs   — HTTP 404
  ❌ Intigriti jobs   — HTTP 404

WORKING (confirmed from run logs):
  ✅ Greenhouse Cybersec: 22 jobs
  ✅ Nitter (CyberSecJobs): 6 jobs
  ✅ GitHub Security Issues: active
  ✅ Telegram public channels: active
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
from sources.new_sources      import fetch_new_sources       # v17: Greenhouse cybersec, Telegram, GitHub
from sources.expanded_sources import fetch_expanded_sources  # v18: 50+ career pages + MENA+

ALL_FETCHERS = [
    # ── 1. Egypt — top priority 🇪🇬 ──────────────────────────
    ("Gov Egypt",            fetch_gov_egypt),      # LinkedIn Egypt companies + gov pages
    ("Egypt Alt",            fetch_egypt_alt),       # Wuzzuf + LinkedIn search/governorates
    ("Egypt Companies",      fetch_egypt_companies), # Security companies + internships

    # ── 2. Gulf 🌙 ────────────────────────────────────────────
    ("Gov Gulf",             fetch_gov_gulf),        # STC, TDRA, Etisalat + LinkedIn Gulf
    ("Gulf Expanded",        fetch_gulf_expanded),   # 40+ Gulf companies + Akhtaboot
    ("Gulf Boards",          fetch_gulf_boards),     # Monster Gulf RSS

    # ── 3. Cybersec-specific boards ──────────────────────────
    ("CyberSec Boards",      fetch_cybersec_boards), # Bugcrowd + HackerOne + BuiltIn

    # ── 4. LinkedIn (global) ──────────────────────────────────
    ("LinkedIn",             fetch_linkedin),
    ("LinkedIn #Hiring",     fetch_linkedin_hiring), # #Hiring posts

    # ── 5. Google Jobs (SerpAPI) ─────────────────────────────
    ("Google Jobs",          fetch_google_jobs),

    # ── 6. Tech boards ───────────────────────────────────────
    ("Tech Boards",          fetch_tech_boards),     # Big Tech Greenhouse

    # ── 7. Remote job boards ─────────────────────────────────
    ("Remotive",             fetch_remotive),
    ("Himalayas",            fetch_himalayas),
    ("Jobicy",               fetch_jobicy),
    ("RemoteOK",             fetch_remoteok),
    ("Arbeitnow",            fetch_arbeitnow),
    ("WWR",                  fetch_wwr),
    ("Working Nomads",       fetch_workingnomads),

    # ── 8. API-based (optional — need keys) ──────────────────
    ("Adzuna",               fetch_adzuna),
    ("Jooble",               fetch_jooble),
    ("Findwork",             fetch_findwork),
    ("Reed",                 fetch_reed),
    # ("JSearch",            fetch_jsearch),  # Uncomment if RAPIDAPI_KEY is set

    # ── 9. Freelance 🔧 ──────────────────────────────────────
    ("Freelance",            fetch_freelance),       # Mostaql + Khamsat + Truelancer

    # ── 10. Creative v17 Sources ──────────────────────────────
    ("New Sources v17",      fetch_new_sources),     # Greenhouse cybersec, Telegram, GitHub, Nitter

    # ── 11. Expanded Sources v18 🚀 ──────────────────────────
    ("Expanded Sources v18", fetch_expanded_sources), # 50+ Greenhouse/Lever, YC, HN Hiring, MENA+
]
