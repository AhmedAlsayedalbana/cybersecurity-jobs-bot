"""
Source registry — ordered by priority:
  1. Gov Egypt:     EG-CERT, ITI, ITIDA, DEPI, NTI, NTRA, MCIT + Egyptian companies
  2. Gov Gulf:      NCA, CITC, SDAIA, Aramco, NEOM, G42, QCERT + Gulf companies + Tanqeeb/Akhtaboot
  3. CyberSec:      Wuzzuf, Bayt, Naukrigulf, Forasna + InfoSec-Jobs, ISACA, ISC2
  4. LinkedIn:      Egypt all govs + Gulf full + Remote
  5. Google Jobs:   SerpAPI + Adzuna MENA
  6. Tech Boards:   Dice, HackerOne, Bugcrowd, Greenhouse
  7. Remote Boards: Remotive, Himalayas, Jobicy, RemoteOK, WWR, etc.
  8. API-based:     Adzuna, Jooble, Findwork, Reed
  9. Freelance:     Upwork, Freelancer, Khamsat, Mustaqil
"""

from sources.gov_egypt       import fetch_gov_egypt
from sources.gov_gulf        import fetch_gov_gulf
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
    # 1. Egyptian Government & Official Institutions (TOP PRIORITY)
    ("Gov Egypt",        fetch_gov_egypt),

    # 2. Gulf Government & Official Institutions
    ("Gov Gulf",         fetch_gov_gulf),

    # 3. Arab Cybersec Boards (Wuzzuf, Bayt, Naukrigulf, Forasna + InfoSec-Jobs...)
    ("CyberSec Boards",  fetch_cybersec_boards),

    # 4. LinkedIn (Egypt all govs + Gulf full + Company pages + Remote)
    ("LinkedIn",         fetch_linkedin),

    # 5. Google Jobs (SerpAPI + Adzuna MENA)
    ("Google Jobs",      fetch_google_jobs),

    # 6. Tech Boards (Dice, HackerOne, Bugcrowd, Greenhouse, Lever)
    ("Tech Boards",      fetch_tech_boards),

    # 7. Remote job boards
    ("Remotive",         fetch_remotive),
    ("Himalayas",        fetch_himalayas),
    ("Jobicy",           fetch_jobicy),
    ("RemoteOK",         fetch_remoteok),
    ("Arbeitnow",        fetch_arbeitnow),
    ("WWR",              fetch_wwr),
    ("Working Nomads",   fetch_workingnomads),

    # 8. API-based (need keys in GitHub Secrets)
    ("Adzuna",           fetch_adzuna),
    ("Jooble",           fetch_jooble),
    ("Findwork",         fetch_findwork),
    ("Reed",             fetch_reed),

    # 9. Freelance (Upwork + Freelancer + Khamsat + Mustaqil)
    ("Freelance",        fetch_freelance),

    # ("JSearch",          fetch_jsearch),  # Optional - RapidAPI key needed
]
