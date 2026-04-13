"""
Job scoring and ranking system for Cybersecurity Jobs Bot.
New Logic:
- Egypt Priority: +12 pts (Increased)
- Remote: +6 pts (Increased)
- Gulf: +4 pts (Increased)
- SIEM/Splunk/AWS Security: +4 pts
- Entry-level (Junior/Intern/Trainee): +5 pts (Increased)
- Freshness: +5 pts
"""

from models import Job, _flatten_tags
from classifier import classify_location
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

def score_job(job: Job) -> int:
    """
    Score a single job with simplified and effective scoring.
    """
    score = 0
    title_text = job.title.lower()
    description_text = job.description.lower()
    tags_text = _flatten_tags(job.tags).lower()
    combined_text = f"{title_text} {description_text} {tags_text}".lower()
    
    # 1. Location Scoring — Egypt & Gulf are TOP PRIORITY
    loc_type = classify_location(job)
    if loc_type == "egypt":
        score += 15   # 🇪🇬 Highest priority
    elif loc_type == "gulf":
        score += 10   # 🌙 Gulf second priority

    # 2. Remote Boost — lower than Gulf now
    if "remote" in combined_text or job.is_remote:
        score += 4

    # 3. High-Value Tech/Skills Boost
    tech_keywords = {
        "siem": 4, "splunk": 4, "qradar": 4, "sentinel": 4,
        "aws security": 4, "cloud security": 4, "azure security": 4,
        "incident response": 3, "soc": 3, "pentest": 3, "penetration": 3,
        "vulnerability": 3, "appsec": 3, "devsecops": 3, "grc": 2,
        "compliance": 2, "iso 27001": 2, "nist": 2
    }
    
    for kw, val in tech_keywords.items():
        if kw in combined_text:
            score += val

    # 4. Freshness Override (High Impact)
    if job.posted_date:
        now = datetime.now()
        diff = now - job.posted_date
        if diff < timedelta(hours=24):
            score += 5
        elif diff > timedelta(days=7): # Relaxed from 5 to 7 days
            score -= 3 # Reduced penalty from -5 to -3

    # 5. Entry-level/Fresh Support — boosted for young professionals
    entry_keywords = ["junior", "intern", "trainee", "fresh grad", "graduate", "entry level", "entry-level"]
    if any(k in combined_text for k in entry_keywords):
        score += 3
    
    exp_keywords = ["0-2 years", "0-1 years", "no experience", "fresh graduate", "1-2 years"]
    if any(k in combined_text for k in exp_keywords):
        score += 2

    # 6. Penalties (Reduced strictness)
    # Only penalize if it's CLEARLY not a security job but passed filters
    if "support" in title_text and not any(k in title_text for k in ["security", "cyber", "soc"]):
        score -= 3 # Reduced from -4
    
    if len(job.title) < 5:
        score -= 5
        
    if not job.url:
        score -= 10

    return score

def sort_by_location_priority(jobs_with_scores: list[tuple[Job, int]]) -> list[tuple[Job, int]]:
    """
    Sort a list of (job, score) tuples by location priority: Egypt > Gulf > Global.
    Within each location, sort by score.
    """
    def loc_priority(item):
        job, score = item
        loc = classify_location(job)
        if loc == "egypt":
            return (0, -score)
        if loc == "gulf":
            return (1, -score)
        return (2, -score)
    
    return sorted(jobs_with_scores, key=loc_priority)
"""
Scoring & Ranking System — V12 (Professional System)
Priority: Egypt 🇪🇬 (Max) → Gulf 🌙 (High) → Remote 🌍 (Medium)
"""

import logging
from models import Job
from classifier import classify_location
from config import EG_PRIVATE_COMPANIES

log = logging.getLogger(__name__)

def score_job(job: Job) -> int:
    """
    Calculate a quality score for a job.
    Higher is better.
    """
    score = 10  # Base score
    
    title = job.title.lower()
    loc_type = classify_location(job)
    
    # 1. Location Multipliers (The Core Priority)
    if loc_type == "egypt":
        score += 25  # Massive boost for Egypt
    elif loc_type == "gulf":
        score += 15  # Strong boost for Gulf
    elif loc_type == "remote":
        score += 8   # Moderate boost for Remote
    
    # 2. Role-based Boosts
    if any(k in title for k in ["pentest", "penetration", "ethical hack", "red team"]):
        score += 12
    if any(k in title for k in ["soc", "threat", "incident", "ir analyst", "blue team"]):
        score += 10
    if any(k in title for k in ["appsec", "application security", "devsecops"]):
        score += 10
    if any(k in title for k in ["cloud security", "aws security", "azure security"]):
        score += 9
    if any(k in title for k in ["grc", "compliance", "risk", "auditor"]):
        score += 7
    if any(k in title for k in ["engineer", "architect"]):
        score += 5
        
    # 3. Company Prestige Boost
    if any(c.lower() in job.company.lower() for c in EG_PRIVATE_COMPANIES):
        score += 10  # Boost for known Egyptian private sector
    
    # 4. Seniority Adjustments
    if any(k in title for k in ["senior", "lead", "principal", "manager", "head", "ciso"]):
        score += 5
    if any(k in title for k in ["junior", "entry", "intern", "trainee", "fresh"]):
        score += 3  # We like entry level too, but slightly less than seniors
        
    # 5. Source Reliability
    if job.source in ["gov_egypt", "gov_gulf", "eg_private"]:
        score += 5
        
    return score

def sort_by_location_priority(jobs_with_scores: list[tuple[Job, int]]) -> list[tuple[Job, int]]:
    """
    Sort a list of (job, score) tuples by location priority: Egypt > Gulf > Global.
    Within each location, sort by score.
    """
    def loc_priority(item):
        job, score = item
        loc = classify_location(job)
        if loc == "egypt":
            return (0, -score)
        if loc == "gulf":
            return (1, -score)
        return (2, -score)
    
    return sorted(jobs_with_scores, key=loc_priority)
