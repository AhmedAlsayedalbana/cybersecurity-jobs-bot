"""
Job scoring and ranking system for Cybersecurity Jobs Bot (v6 - Elite Pro).
New Logic:
- Egypt Priority: +10 pts
- Remote: +4 pts
- SIEM/Splunk/AWS Security: +3 pts
- Entry-level (Junior/Intern/Trainee): +2 to +3 pts
- Penalty for noise (Support): -4 pts
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
    
    # 1. Location Scoring
    loc_type = classify_location(job)
    if loc_type == "egypt":
        score += 10
    elif loc_type == "gulf":
        score += 1  # Gulf gets a small boost over global
    
    # 2. Remote Boost
    if "remote" in combined_text or job.is_remote:
        score += 3

    # 3. High-Value Tech/Skills Boost
    if "siem" in combined_text:
        score += 3
    if "splunk" in combined_text:
        score += 3
    if "aws security" in combined_text or "cloud security" in combined_text:
        score += 3
    if "incident response" in combined_text:
        score += 4
    if "soc" in combined_text:
        score += 4
    if "pentest" in combined_text:
        score += 3

    # 4. Freshness Override (High Impact)
    if job.posted_date:
        now = datetime.now()
        diff = now - job.posted_date
        if diff < timedelta(hours=24):
            score += 5
        elif diff > timedelta(days=5):
            score -= 5

    # 5. Entry-level/Fresh Support & "Opportunity Boost"
    if any(k in combined_text for k in ["junior", "intern", "trainee", "fresh grad"]):
        score += 3
    if any(k in combined_text for k in ["0-2 years", "0-1 years", "no experience", "entry level"]):
        score += 4  # "Power Move" boost for early-career opportunities

    # 6. Penalties (Noise Reduction)
    if "support" in title_text:
        score -= 4
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
