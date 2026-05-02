"""
Source registry — v37

CHANGES vs v36:
  ✅ MEMORY_DAYS: 7→3 (see dedup.py & database.py) — was blocking 92% of results
  ✅ BUDGETS raised: egypt_companies 120→240s, gov_egypt 300→420s+150→240s,
                     gov_gulf 300→420s — retry sleep time not previously counted
  ✅ WUZZUF: switched HTML scraping → RSS feed (bypasses Cloudflare JS challenge)
  ✅ RE-ENABLED free non-LinkedIn sources for redundancy:
      - Remotive API   (no key, remote cybersec roles)
      - Arbeitnow API  (no key, clean JSON, international)
      - WWR RSS        (no key, DevOps/SysAdmin → security filtered)
  ✅ DB table bug fixed: job_bot.yml was querying seen_jobs → now queries jobs
  ✅ Added NOTE in scoring.py about README vs actual WEIGHTS discrepancy
  ✅ linkedin_hiring.py: fixed SENDING bug — jobs were fetched but never sent

ACTIVE SOURCES (12 fetchers):
  1. Gov Egypt          — LinkedIn: Egyptian gov & major co. security roles
  2. Egypt Alt          — LinkedIn: Egypt alternate / private sector + Wuzzuf RSS
  3. Egypt Companies    — LinkedIn: 150+ Egypt security companies
  4. Gov Gulf           — LinkedIn: Gulf gov & majors (STC, Aramco, etc.)
  5. Gulf Expanded      — LinkedIn: Gulf broader search + internships
  6. LinkedIn Core      — Guest API: Egypt + Gulf + Remote (52 queries)
  7. LinkedIn #Hiring   — Guest API: #Hiring keyword focused (21 queries)
  8. LinkedIn Posts     — HR post search style (14 queries)
  9. LinkedIn HR Hunter — Blue/Red/Specialist hunter (20 queries)
 10. Remotive           — Free API: remote cybersecurity roles globally
 11. Arbeitnow          — Free API: international security roles (JSON)
 12. WWR                — Free RSS: remote DevOps/SysAdmin → security filtered
"""

from sources.gov_egypt          import fetch_gov_egypt
from sources.egypt_alt          import fetch_egypt_alt
from sources.egypt_companies    import fetch_egypt_companies
from sources.gov_gulf           import fetch_gov_gulf
from sources.gulf_expanded      import fetch_gulf_expanded
from sources.linkedin           import fetch_linkedin
from sources.linkedin_hiring    import fetch_linkedin_hiring
from sources.linkedin_posts     import fetch_linkedin_posts
from sources.linkedin_hr_hunter import fetch_linkedin_hr_hunter
from sources.remotive           import fetch_remotive
from sources.arbeitnow          import fetch_arbeitnow
from sources.wwr                import fetch_wwr

ALL_FETCHERS = [
    # ── 1. Egypt 🇪🇬 (highest priority) ──────────────────────
    ("Gov Egypt",          fetch_gov_egypt),
    ("Egypt Alt",          fetch_egypt_alt),
    ("Egypt Companies",    fetch_egypt_companies),

    # ── 2. Gulf 🌙 ────────────────────────────────────────────
    ("Gov Gulf",           fetch_gov_gulf),
    ("Gulf Expanded",      fetch_gulf_expanded),

    # ── 3. LinkedIn (all 4 fetchers, max coverage) ────────────
    ("LinkedIn",           fetch_linkedin),
    ("LinkedIn #Hiring",   fetch_linkedin_hiring),
    ("LinkedIn Posts",     fetch_linkedin_posts),
    ("LinkedIn HR Hunter", fetch_linkedin_hr_hunter),

    # ── 4. Free APIs (no key needed, redundancy) ─────────────
    ("Remotive",           fetch_remotive),
    ("Arbeitnow",          fetch_arbeitnow),
    ("WWR",                fetch_wwr),
]
