"""
Source Registry — V12 (Professional System)
Priority: Egypt 🇪🇬 → Gulf 🌙 → Remote 🌍

Removed optional API-based sources to eliminate warnings.
"""

from sources.gov_egypt import fetch_gov_egypt
from sources.gov_gulf import fetch_gov_gulf
from sources.cybersec_boards import fetch_cybersec_boards
from sources.egypt_alt import fetch_egypt_alt
from sources.linkedin import fetch_linkedin
from sources.google_jobs import fetch_google_jobs
from sources.tech_boards import fetch_tech_boards
from sources.remotive import fetch_remotive
from sources.himalayas import fetch_himalayas
from sources.jobicy import fetch_jobicy
from sources.remoteok import fetch_remoteok
from sources.arbeitnow import fetch_arbeitnow
from sources.wwr import fetch_wwr
from sources.workingnomads import fetch_workingnomads
from sources.freelance import fetch_freelance

# Ordered by priority: Egypt & Gulf first, then Global
ALL_FETCHERS = [
    # 1. Egypt Priority
    ("Gov Egypt",       fetch_gov_egypt),
    ("Egypt Alt",       fetch_egypt_alt),
    
    # 2. Gulf Priority
    ("Gov Gulf",        fetch_gov_gulf),
    
    # 3. Targeted Cyber Boards
    ("CyberSec Boards", fetch_cybersec_boards),
    
    # 4. Smart Search (Google/LinkedIn)
    ("LinkedIn",        fetch_linkedin),
    ("Google Jobs",     fetch_google_jobs),
    
    # 5. General Tech & Remote Boards
    ("Tech Boards",     fetch_tech_boards),
    ("Remotive",        fetch_remotive),
    ("Himalayas",       fetch_himalayas),
    ("Jobicy",          fetch_jobicy),
    ("RemoteOK",        fetch_remoteok),
    ("Arbeitnow",       fetch_arbeitnow),
    ("WWR",             fetch_wwr),
    ("WorkingNomads",   fetch_workingnomads),
    
    # 6. Freelance
    ("Freelance",       fetch_freelance),
]
