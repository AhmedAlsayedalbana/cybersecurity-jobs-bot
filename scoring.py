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
