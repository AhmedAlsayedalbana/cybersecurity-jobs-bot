"""
Source registry — v15

PRIORITY ORDER:
  1. Egypt (🇪🇬) — All governorates, public + private sector + #Hiring posts
  2. Egypt expanded — Security companies, internships, DrJobPro, Akhtaboot
  3. Gulf (🌙) — KSA, UAE, Kuwait, Qatar, Bahrain, Oman + expanded companies
  4. Gulf expanded — Internships, Akhtaboot, Naukrigulf
  5. Cybersec boards (global)
  6. LinkedIn (global jobs + #Hiring posts)
  7. Google Jobs (SerpAPI)
  8. Tech boards
  9. Remote job boards
  10. API-based (optional — need keys)
  11. Freelance (Arab + global)
"""

from sources.gov_egypt        import fetch_gov_egypt
from sources.egypt_alt        import fetch_egypt_alt
from sources.egypt_companies  import fetch_egypt_companies   # NEW v15
from sources.gov_gulf         import fetch_gov_gulf
from sources.gulf_expanded    import fetch_gulf_expanded     # NEW v15
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

ALL_FETCHERS = [
    # ── 1. Egypt — top priority 🇪🇬 ──────────────────────────
    ("Gov Egypt",           fetch_gov_egypt),       # LinkedIn Egypt companies + gov pages
    ("Egypt Alt",           fetch_egypt_alt),        # Wuzzuf + LinkedIn search/governorates
    ("Egypt Companies",     fetch_egypt_companies),  # Expanded security companies + internships

    # ── 2. Gulf 🌙 ────────────────────────────────────────────
    ("Gov Gulf",            fetch_gov_gulf),         # STC, TDRA, Etisalat + LinkedIn Gulf
    ("Gulf Expanded",       fetch_gulf_expanded),    # 40+ Gulf companies + internships + Akhtaboot
    ("Gulf Boards",         fetch_gulf_boards),      # Monster Gulf RSS

    # ── 3. Cybersec-specific boards ──────────────────────────
    ("CyberSec Boards",     fetch_cybersec_boards),  # Bugcrowd + HackerOne + BuiltIn

    # ── 4. LinkedIn (global) ──────────────────────────────────
    ("LinkedIn",            fetch_linkedin),
    ("LinkedIn #Hiring",    fetch_linkedin_hiring),  # #Hiring posts — human-sourced leads

    # ── 5. Google Jobs (SerpAPI) ─────────────────────────────
    ("Google Jobs",         fetch_google_jobs),

    # ── 6. Tech boards ───────────────────────────────────────
    ("Tech Boards",         fetch_tech_boards),      # Big Tech Greenhouse (security roles)

    # ── 7. Remote job boards ─────────────────────────────────
    ("Remotive",            fetch_remotive),
    ("Himalayas",           fetch_himalayas),
    ("Jobicy",              fetch_jobicy),
    ("RemoteOK",            fetch_remoteok),
    ("Arbeitnow",           fetch_arbeitnow),
    ("WWR",                 fetch_wwr),
    ("Working Nomads",      fetch_workingnomads),

    # ── 8. API-based (optional — need keys) ──────────────────
    ("Adzuna",              fetch_adzuna),
    ("Jooble",              fetch_jooble),
    ("Findwork",            fetch_findwork),
    ("Reed",                fetch_reed),
    # ("JSearch",           fetch_jsearch),  # Uncomment if RAPIDAPI_KEY is set

    # ── 9. Freelance 🔧 ──────────────────────────────────────
    ("Freelance",           fetch_freelance),        # Mostaql + Khamsat + Truelancer
]
"""
Source registry — v12 updated

PRIORITY ORDER:
  1. Egypt (🇪🇬) — All governorates, public + private sector + #Hiring posts
  2. Gulf (🌙) — KSA, UAE, Kuwait, Qatar, Bahrain, Oman + #Hiring posts
  3. Cybersec boards (global)
  4. LinkedIn (global jobs + #Hiring posts)
  5. Google Jobs (SerpAPI)
  6. Tech boards
  7. Remote job boards
  8. API-based (optional — need keys)
  9. Freelance (Arab + global)

REMOVED DEAD SOURCES:
  ❌ Bayt Egypt / Gulf       — 403 Forbidden
  ❌ Naukrigulf Egypt / Gulf  — timeout (10s)
  ❌ Forasna                  — 404 Not Found
  ❌ Tanqeeb                  — 403 Forbidden
  ❌ GulfTalent               — 403 Forbidden
  ❌ Saudi Greenhouse slugs   — 404 Not Found
  ❌ CyberSec Greenhouse slugs— 404 Not Found
  ❌ Lever slugs              — 404 Not Found
  ❌ The Muse                 — 0 results
  ❌ Indeed RSS               — 403 Forbidden

ACTIVE SOURCES:
  ✅ LinkedIn (jobs + #Hiring)
  ✅ Gov Egypt (company pages + LinkedIn)
  ✅ Egypt Alt (Wuzzuf + LinkedIn search/governorates)
  ✅ Gov Gulf (STC, TDRA, Etisalat + LinkedIn Gulf)
  ✅ Gulf Boards (Monster Gulf RSS)
  ✅ CyberSec Boards (CyberSecJobs, Bugcrowd, HackerOne, BuiltIn)
  ✅ Tech Boards (Big Tech Greenhouse)
  ✅ Remote boards (Remotive, Himalayas, Jobicy, RemoteOK, Arbeitnow, WWR, WorkingNomads)
  ✅ Freelance (Mostaql, Khamsat, Truelancer, WorkInSecurity)
"""

from sources.gov_egypt       import fetch_gov_egypt
from sources.egypt_alt       import fetch_egypt_alt
from sources.gov_gulf        import fetch_gov_gulf
from sources.gulf_boards     import fetch_gulf_boards
from sources.cybersec_boards import fetch_cybersec_boards
from sources.linkedin        import fetch_linkedin
from sources.linkedin_hiring import fetch_linkedin_hiring
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
    # ── 1. Egypt — top priority 🇪🇬 ──────────────────────────
    ("Gov Egypt",        fetch_gov_egypt),       # LinkedIn Egypt companies + gov pages
    ("Egypt Alt",        fetch_egypt_alt),        # Wuzzuf + LinkedIn search/governorates

    # ── 2. Gulf 🌙 ────────────────────────────────────────────
    ("Gov Gulf",         fetch_gov_gulf),         # STC, TDRA, Etisalat + LinkedIn Gulf
    ("Gulf Boards",      fetch_gulf_boards),      # Monster Gulf RSS

    # ── 3. Cybersec-specific boards ──────────────────────────
    ("CyberSec Boards",  fetch_cybersec_boards),  # CyberSecJobs + Bugcrowd + HackerOne + BuiltIn

    # ── 4. LinkedIn (global) ──────────────────────────────────
    ("LinkedIn",         fetch_linkedin),
    ("LinkedIn #Hiring", fetch_linkedin_hiring),  # #Hiring posts — human-sourced leads

    # ── 5. Google Jobs (SerpAPI) ─────────────────────────────
    ("Google Jobs",      fetch_google_jobs),

    # ── 6. Tech boards ───────────────────────────────────────
    ("Tech Boards",      fetch_tech_boards),      # Big Tech Greenhouse (security roles)

    # ── 7. Remote job boards ─────────────────────────────────
    ("Remotive",         fetch_remotive),
    ("Himalayas",        fetch_himalayas),
    ("Jobicy",           fetch_jobicy),
    ("RemoteOK",         fetch_remoteok),
    ("Arbeitnow",        fetch_arbeitnow),
    ("WWR",              fetch_wwr),
    ("Working Nomads",   fetch_workingnomads),

    # ── 8. API-based (optional — need keys) ──────────────────
    ("Adzuna",           fetch_adzuna),
    ("Jooble",           fetch_jooble),
    ("Findwork",         fetch_findwork),
    ("Reed",             fetch_reed),
    # ("JSearch",        fetch_jsearch),  # Uncomment if RAPIDAPI_KEY is set

    # ── 9. Freelance 🔧 ──────────────────────────────────────
    ("Freelance",        fetch_freelance),        # Mostaql + Khamsat + Truelancer + WorkInSecurity
]
"""
Source registry V12 — Zero-Warning Edition

PRIORITY ORDER:
  1. Egypt (🇪🇬) — All governorates, public + private sector
  2. Gulf (🌙) — KSA, UAE, Kuwait, Qatar, Bahrain, Oman  
  3. Cybersec boards (global)
  4. LinkedIn (global)
  5. Google Jobs (SerpAPI)
  6. Tech boards (reliable only)
  7. Remote job boards (all confirmed working)
  8. API-based (optional — need keys)
  9. Freelance (Arab + global)

CHANGES v12 vs v11:
  ✅ egypt_alt:       Replaced all dead company pages with Bayt/Naukrigulf/Tanqeeb/Forasna
                     Added LinkedIn private sector Egypt (21 companies)
                     Added LinkedIn by governorate (7 tech hubs)
                     Removed dead Wuzzuf API → HTML-only scrape
                     Removed dead Greenhouse slugs (vezeeta etc.)
  ✅ gov_gulf:        Added LinkedIn Gulf keyword search
                     Added Bayt Gulf + Naukrigulf Gulf
                     Expanded LinkedIn Gulf companies (19 companies)
  ✅ gulf_boards:     NEW — GulfTalent + Saudi Greenhouse + Monster Gulf  
  ✅ cybersec_boards: Removed all dead Greenhouse/Lever slugs
                     Added verified working slugs only
                     Added HackerOne + BuiltIn scrape
  ✅ tech_boards:     Replaced all dead boards with The Muse + Indeed RSS + Big Tech Greenhouse
  ✅ freelance:       Removed PeoplePerHour + Guru (dead)
                     Added WorkInSecurity.co.uk
  ✅ gov_egypt:       Already working — untouched

RESULT: Zero WARNING-level logs expected from known-dead endpoints
"""

from sources.gov_egypt       import fetch_gov_egypt
from sources.egypt_alt       import fetch_egypt_alt
from sources.gov_gulf        import fetch_gov_gulf
from sources.gulf_boards     import fetch_gulf_boards
from sources.cybersec_boards import fetch_cybersec_boards
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
    # ── 1. Egypt — top priority 🇪🇬 ──────────────────────────
    ("Gov Egypt",       fetch_gov_egypt),      # LinkedIn Egypt companies + governorates
    ("Egypt Alt",       fetch_egypt_alt),       # Wuzzuf + Bayt + Naukrigulf + Forasna + Tanqeeb
                                                # + LinkedIn Egypt search + private sector

    # ── 2. Gulf 🌙 ────────────────────────────────────────────
    ("Gov Gulf",        fetch_gov_gulf),        # STC, TDRA, Etisalat + LinkedIn Gulf + Bayt/Naukrigulf
    ("Gulf Boards",     fetch_gulf_boards),     # GulfTalent + Saudi Greenhouse + Monster Gulf

    # ── 3. Cybersec-specific boards ──────────────────────────
    ("CyberSec Boards", fetch_cybersec_boards), # CyberSecJobs + Bugcrowd + Greenhouse + Lever
                                                # + HackerOne + BuiltIn

    # ── 4. LinkedIn (global) ──────────────────────────────────
    ("LinkedIn",        fetch_linkedin),

    # ── 5. Google Jobs (SerpAPI) ─────────────────────────────
    ("Google Jobs",     fetch_google_jobs),

    # ── 6. Tech boards (reliable) ────────────────────────────
    ("Tech Boards",     fetch_tech_boards),     # The Muse + Indeed RSS + Big Tech Greenhouse

    # ── 7. Remote job boards (all confirmed live) ─────────────
    ("Remotive",        fetch_remotive),        # 44 jobs confirmed
    ("Himalayas",       fetch_himalayas),       # 300 jobs confirmed
    ("Jobicy",          fetch_jobicy),          # 100 jobs confirmed
    ("RemoteOK",        fetch_remoteok),        # 95 jobs confirmed
    ("Arbeitnow",       fetch_arbeitnow),       # 100 jobs confirmed
    ("WWR",             fetch_wwr),             # 108 jobs confirmed
    ("Working Nomads",  fetch_workingnomads),   # 19 jobs confirmed

    # ── 8. API-based (optional — need keys) ──────────────────
    ("Adzuna",          fetch_adzuna),
    ("Jooble",          fetch_jooble),
    ("Findwork",        fetch_findwork),
    ("Reed",            fetch_reed),
    # ("JSearch",       fetch_jsearch),  # Uncomment if RAPIDAPI_KEY is set

    # ── 9. Freelance 🔧 ──────────────────────────────────────
    ("Freelance",       fetch_freelance),       # Mostaql + Khamsat + Truelancer + WorkInSecurity
]
