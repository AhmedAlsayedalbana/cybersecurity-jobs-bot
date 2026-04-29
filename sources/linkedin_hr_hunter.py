"""
LinkedIn HR Hunter — v35 (FIXED)
=================================
Previous version used Google site: search → 429 on every query → 0 jobs.
This version uses LinkedIn jobs-guest API directly (same as linkedin_posts.py),
focusing on HR-style keywords that catch informal postings.

No Google scraping. No Anthropic API calls per job. Fast & clean.
"""

import logging
import re
import time
import random
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

MAX_BUDGET_SECS = 3 * 60  # 3 min budget

_BASE = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

# HR-style keywords unlikely to be covered by other LinkedIn fetchers
_SEARCHES = [
    {"keywords": "security operations center",   "location": "Egypt",         "f_TPR": "r259200"},
    {"keywords": "blue team",                     "location": "Egypt",         "f_TPR": "r259200"},
    {"keywords": "red team",                      "location": "Egypt",         "f_TPR": "r259200"},
    {"keywords": "DFIR",                          "location": "Egypt",         "f_TPR": "r259200"},
    {"keywords": "vulnerability assessment",      "location": "Egypt",         "f_TPR": "r259200"},
    {"keywords": "cyber threat intelligence",     "location": "Egypt",         "f_TPR": "r259200"},
    {"keywords": "security operations center",   "location": "Saudi Arabia",   "f_TPR": "r259200"},
    {"keywords": "blue team",                     "location": "Saudi Arabia",   "f_TPR": "r259200"},
    {"keywords": "red team",                      "location": "UAE",            "f_TPR": "r259200"},
    {"keywords": "DFIR",                          "location": "Saudi Arabia",   "f_TPR": "r259200"},
]

_ROLE_MAP = [
    (["soc analyst", "security operations analyst"],           "SOC Analyst"),
    (["soc engineer", "security operations engineer"],         "SOC Engineer"),
    (["blue team"],                                            "Blue Team Analyst"),
    (["red team"],                                             "Red Team Engineer"),
    (["dfir", "incident resp"],                                "Incident Response / DFIR"),
    (["threat intel", "cti"],                                  "Threat Intelligence Analyst"),
    (["vulnerability", "vapt"],                                "Vulnerability Assessment Analyst"),
    (["penetration tester", "pentester"],                      "Penetration Tester"),
    (["malware analyst"],                                      "Malware Analyst"),
    (["security engineer", "cybersecurity engineer"],          "Security Engineer"),
    (["security analyst"],                                     "Security Analyst"),
    (["cybersecurity", "cyber security"],                      "Cybersecurity Specialist"),
]

def _match_title(raw: str) -> str:
    t = raw.lower()
    for kws, canonical in _ROLE_MAP:
        if any(k in t for k in kws):
            return canonical
    return raw.strip().title()


def fetch_linkedin_hr_hunter() -> list[Job]:
    jobs: list[Job] = []
    seen: set = set()
    start = time.time()

    for s in _SEARCHES:
        if time.time() - start > MAX_BUDGET_SECS:
            log.warning("HR Hunter: budget exhausted early")
            break

        params = {**s, "start": "0", "count": "10"}
        html = get_text(_BASE, params=params)
        if not html or len(html) < 200:
            time.sleep(2)
            continue

        job_ids   = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        titles    = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', html)
        companies = re.findall(r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>\s*<a[^>]*>([^<]+)', html)
        locations = re.findall(r'<span[^>]*class="[^"]*job-search-card__location[^"]*"[^>]*>\s*([^<]+)', html)

        for i, title in enumerate(titles):
            title = title.strip()
            if not title or title in seen:
                continue
            seen.add(title)
            job_id  = job_ids[i] if i < len(job_ids) else ""
            company = companies[i].strip() if i < len(companies) else "Unknown"
            raw_loc = locations[i].strip() if i < len(locations) else ""
            location = raw_loc if raw_loc else s.get("location", "Egypt")
            jobs.append(Job(
                title=_match_title(title),
                company=company,
                location=location,
                url=f"https://www.linkedin.com/jobs/view/{job_id}/" if job_id else _BASE,
                source="linkedin_hr_post",
                original_source=f"LinkedIn HR — {s.get('keywords', '')}",
                tags=["linkedin", "hr-search", location.split(",")[0].lower()],
                is_remote=False,
            ))
        time.sleep(random.uniform(2, 3))

    log.info(f"LinkedIn HR Hunter: found {len(jobs)} HR posts")
    return jobs
