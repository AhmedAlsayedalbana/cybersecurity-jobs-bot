"""
Job scoring and ranking system for Cybersecurity Jobs Bot.
Scoring Philosophy:
- Egypt Priority: +8 pts (preferred but not overwhelming)
- Gulf: +6 pts (strong second)
- Remote: +5 pts (close to Gulf — remote jobs are very relevant)
- Specialized skills: up to +4 pts
- Entry-level support: +3 pts
- Freshness: +5 pts
"""

from models import Job, _flatten_tags
from classifier import classify_location
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

def score_job(job: Job) -> int:
    """
    Score a single job. Balanced scoring — Egypt first, but Remote/Gulf are competitive.
    """
    score = 0
    title_text = job.title.lower()
    description_text = job.description.lower()
    tags_text = _flatten_tags(job.tags).lower()
    combined_text = f"{title_text} {description_text} {tags_text}".lower()

    # 1. Location Scoring — Egypt preferred, Gulf and Remote are close
    loc_type = classify_location(job)
    if loc_type == "egypt":
        score += 8    # Egypt first, but not overwhelming
    elif loc_type == "gulf":
        score += 6    # Gulf is a strong second
    elif "remote" in combined_text or job.is_remote:
        score += 5    # Remote is nearly as good as Gulf

    # 2. Additional remote boost if also Egypt/Gulf (hybrid)
    if ("remote" in combined_text or job.is_remote) and loc_type in ("egypt", "gulf"):
        score += 2

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

    # 4. Freshness
    if job.posted_date:
        now = datetime.now()
        diff = now - job.posted_date
        if diff < timedelta(hours=24):
            score += 5
        elif diff > timedelta(days=7):
            score -= 3

    # 5. Entry-level support
    entry_keywords = ["junior", "intern", "trainee", "fresh grad", "graduate", "entry level", "entry-level"]
    if any(k in combined_text for k in entry_keywords):
        score += 3

    exp_keywords = ["0-2 years", "0-1 years", "no experience", "fresh graduate", "1-2 years"]
    if any(k in combined_text for k in exp_keywords):
        score += 2

    # 6. Penalties
    if "support" in title_text and not any(k in title_text for k in ["security", "cyber", "soc"]):
        score -= 3

    if len(job.title) < 5:
        score -= 5

    if not job.url:
        score -= 10

    return score


def sort_by_location_priority(jobs_with_scores: list[tuple[Job, int]]) -> list[tuple[Job, int]]:
    """
    Sort (job, score) by location priority: Egypt > Gulf > Global.
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

