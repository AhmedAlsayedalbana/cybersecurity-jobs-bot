"""
Source registry — v36 (LinkedIn-Only Edition)

CHANGES vs v34:
  🗑️  REMOVED ALL NON-LINKEDIN SOURCES:
      - Adzuna          (API key required, low relevance)
      - Jooble          (noisy, low Egypt/Gulf quality)
      - GitHub Jobs     (irrelevant to MENA market)
      - GitLab Jobs     (irrelevant to MENA market)
      - Telegram Channels (unreliable, 2 jobs per run)
      - Hacker News Hiring (0 jobs last run)
      - Google Jobs/SerpAPI (always 0, rate-limited)
      - Wuzzuf scraper  (0 jobs last run)
      - Findwork        (API key required, skipped)
      - Reed            (UK-only, API key required)
      - Remotive        (generic remote, low MENA relevance)
      - RemoteOK        (generic remote, low MENA relevance)
      - Arbeitnow       (generic remote, irrelevant)
      - WWR             (generic remote, irrelevant)
      - Working Nomads  (generic remote, irrelevant)
      - Tech Boards     (Greenhouse noisy US-only)
      - New Sources v27 (GitHub+Telegram=dead)
      - Expanded Sources (Greenhouse = mostly US/EU)
      - CyberSec Boards (Bugcrowd = 6 jobs only, not MENA)
      - Arab Boards     (all 403/404 dead confirmed)

  ✅  KEPT: All 9 LinkedIn-backed sources
  ✅  EXPANDED linkedin.py: +10 Egypt searches, +8 Gulf, +4 Remote
  ✅  EXPANDED linkedin_hiring.py: +8 Egypt searches, +4 Gulf, +4 Junior
  ✅  EXPANDED linkedin_hr_hunter.py: +10 specialized search terms
  ✅  EXPANDED linkedin_posts.py: +6 Egypt HR searches

ACTIVE SOURCES (LinkedIn only — 9 fetchers):
  1. Gov Egypt          — LinkedIn: Egyptian gov & major co. security roles
  2. Egypt Alt          — LinkedIn: Egypt alternate / private sector
  3. Egypt Companies    — LinkedIn: 150+ Egypt security companies
  4. Gov Gulf           — LinkedIn: Gulf gov & majors (STC, Aramco, etc.)
  5. Gulf Expanded      — LinkedIn: Gulf broader search + internships
  6. LinkedIn Core      — Guest API: Egypt + Gulf + Remote (52 queries)
  7. LinkedIn #Hiring   — Guest API: #Hiring keyword focused (21 queries)
  8. LinkedIn Posts     — HR post search style (14 queries)
  9. LinkedIn HR Hunter — Blue/Red/Specialist hunter (20 queries)
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
]
