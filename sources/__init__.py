"""
Source registry — ordered by priority:
  1. CyberSec Boards: Wuzzuf, Bayt, Naukrigulf, Forasna + InfoSec-Jobs, ISACA...
  2. LinkedIn: Egypt all govs + Gulf full + Remote
  3. Tech Boards: Dice, HackerOne, Bugcrowd, Greenhouse
  4. Remote Boards: Remotive, Himalayas, Jobicy, RemoteOK, etc.
  5. API-based: Adzuna, Jooble, Findwork, Reed
  6. Freelance: Upwork, Freelancer, Khamsat, Mustaqil
"""

from sources.cybersec_boards import fetch_cybersec_boards
from sources.linkedin        import fetch_linkedin
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
    # 1. CyberSec Boards (Wuzzuf + Bayt + Naukrigulf + Forasna + InfoSec-Jobs...)
    ("CyberSec Boards",  fetch_cybersec_boards),

    # 2. LinkedIn (Egypt all govs + Gulf full + Remote)
    ("LinkedIn",         fetch_linkedin),

    # 3. Tech Boards
    ("Tech Boards",      fetch_tech_boards),

    # 4. Remote job boards
    ("Remotive",         fetch_remotive),
    ("Himalayas",        fetch_himalayas),
    ("Jobicy",           fetch_jobicy),
    ("RemoteOK",         fetch_remoteok),
    ("Arbeitnow",        fetch_arbeitnow),
    ("WWR",              fetch_wwr),
    ("Working Nomads",   fetch_workingnomads),

    # 5. API-based (need keys in GitHub Secrets)
    ("Adzuna",           fetch_adzuna),
    ("Jooble",           fetch_jooble),
    ("Findwork",         fetch_findwork),
    ("Reed",             fetch_reed),

    # 6. Freelance (Upwork + Freelancer + Khamsat + Mustaqil)
    ("Freelance",        fetch_freelance),

    # ("JSearch",          fetch_jsearch),  # Optional - RapidAPI key needed
]
