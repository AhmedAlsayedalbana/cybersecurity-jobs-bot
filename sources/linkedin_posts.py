"""
LinkedIn Posts Scraper � v31
Strategy: scrape LinkedIn public post search for "#hiring" + cybersecurity keywords.
This catches HR professionals posting job openings as posts (not job listings),
which is what was missing from linkedin_hiring.py.

Uses Nitter/Google cache approach as LinkedIn post search is heavily restricted.
Falls back to direct LinkedIn post search when available.
"""

import logging
import re
import time
import random
import urllib.parse
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

_ROLE_MAP = [
    (["soc analyst", "security operations analyst"],           "SOC Analyst"),
    (["soc engineer", "security operations engineer"],         "SOC Engineer"),
    (["siem", "security monitoring"],                          "SIEM / Security Monitoring"),
    (["threat intel", "threat intelligence", "cti"],           "Threat Intelligence Analyst"),
    (["threat hunter", "threat hunting"],                      "Threat Hunter"),
    (["incident resp", "ir analyst", "dfir"],                  "Incident Response / DFIR"),
    (["malware analyst", "malware researcher", "reverse eng"], "Malware Analyst"),
    (["penetration tester", "pen tester", "pentester"],        "Penetration Tester"),
    (["red team", "red teamer"],                               "Red Team Engineer"),
    (["ethical hack", "bug bounty"],                           "Ethical Hacker / Bug Bounty"),
    (["appsec", "application security"],                       "Application Security Engineer"),
    (["devsecops", "dev sec ops"],                             "DevSecOps Engineer"),
    (["cloud security", "aws security", "azure security"],     "Cloud Security Engineer"),
    (["network security", "firewall"],                         "Network Security Engineer"),
    (["grc", "governance risk", "compliance", "iso 27001"],    "GRC / Compliance Analyst"),
    (["ciso", "chief information security"],                   "CISO"),
    (["security architect"],                                   "Security Architect"),
    (["security engineer", "cybersecurity engineer"],          "Security Engineer"),
    (["intern", "trainee", "fresh grad", "junior security"],   "Security Intern / Junior"),
    (["cybersecurity", "cyber security", "infosec"],           "Cybersecurity Specialist"),
    (["security analyst", "security specialist"],              "Security Analyst"),
]

def _match_title(raw: str) -> str:
    t = raw.lower()
    for kws, canonical in _ROLE_MAP:
        if any(k in t for k in kws):
            return canonical
    return raw.strip().title()


def _fetch_via_linkedin_search_api():
    """
    LinkedIn jobs search � searches with HR-style keywords across Egypt & Gulf.
    v33: Expanded searches, added location extraction, multi-keyword support.
    """
    from sources.http_utils import get_text as _get
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

    # Focused searches � top HR keywords for Egypt & Gulf (expanded v43)
    searches = [
        # Egypt � English
        {"keywords": "SOC analyst",                 "location": "Egypt",        "f_TPR": "r259200"},
        {"keywords": "penetration tester",           "location": "Egypt",        "f_TPR": "r259200"},
        {"keywords": "cybersecurity engineer",       "location": "Egypt",        "f_TPR": "r259200"},
        {"keywords": "information security",         "location": "Egypt",        "f_TPR": "r259200"},
        {"keywords": "GRC analyst",                  "location": "Egypt",        "f_TPR": "r259200"},
        {"keywords": "security intern",              "location": "Egypt",        "f_TPR": "r604800"},
        {"keywords": "cloud security",               "location": "Egypt",        "f_TPR": "r259200"},
        {"keywords": "incident response",            "location": "Egypt",        "f_TPR": "r259200"},
        {"keywords": "security analyst",             "location": "Egypt",        "f_TPR": "r259200"},
        {"keywords": "devsecops",                    "location": "Egypt",        "f_TPR": "r259200"},
        # Egypt � Arabic
        {"keywords": "Ø£Ù…Ù† Ø³ÙŠØ¨Ø±Ø§Ù†ÙŠ",            "location": "Egypt",        "f_TPR": "r259200"},
        {"keywords": "Ù…Ø­Ù„Ù„ Ø£Ù…Ù† Ù…Ø¹Ù„ÙˆÙ…Ø§Øª",      "location": "Egypt",        "f_TPR": "r259200"},
        {"keywords": "Ù…Ù‡Ù†Ø¯Ø³ Ø£Ù…Ù† Ø´Ø¨ÙƒØ§Øª",       "location": "Egypt",        "f_TPR": "r259200"},
        # Egypt � Cities
        {"keywords": "cybersecurity",               "location": "Cairo, Egypt", "f_TPR": "r259200"},
        {"keywords": "information security",        "location": "Cairo, Egypt", "f_TPR": "r259200"},
        {"keywords": "cybersecurity",               "location": "Alexandria, Egypt", "f_TPR": "r259200"},
        # Saudi Arabia
        {"keywords": "SOC analyst",                 "location": "Saudi Arabia", "f_TPR": "r259200"},
        {"keywords": "cybersecurity engineer",      "location": "Saudi Arabia", "f_TPR": "r259200"},
        {"keywords": "GRC analyst",                 "location": "Saudi Arabia", "f_TPR": "r259200"},
        {"keywords": "information security",        "location": "Saudi Arabia", "f_TPR": "r259200"},
        # UAE
        {"keywords": "SOC analyst",                 "location": "United Arab Emirates", "f_TPR": "r259200"},
        {"keywords": "cybersecurity engineer",      "location": "Dubai, UAE",           "f_TPR": "r259200"},
        {"keywords": "cloud security",              "location": "Dubai, UAE",           "f_TPR": "r259200"},
        # Other Gulf
        {"keywords": "cybersecurity",               "location": "Qatar",                "f_TPR": "r259200"},
        {"keywords": "cybersecurity",               "location": "Kuwait",               "f_TPR": "r259200"},
    ]

    BUDGET_SECS = 300  # v43: 5 min max for this source
    t0 = time.time()

    for s in searches:
        if time.time() - t0 > BUDGET_SECS:
            log.info(f"linkedin_posts: {BUDGET_SECS}s budget hit � stopping early")
            break
        params = {k: v for k, v in s.items()}
        params.update({"start": "0", "count": "15"})
        html = _get(base, params=params)
        if not html or len(html) < 200:
            time.sleep(3)
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
            job_id   = job_ids[i] if i < len(job_ids) else ""
            company  = companies[i].strip() if i < len(companies) else "Unknown"
            # Use actual scraped location if available, otherwise fall back to search location
            raw_loc  = locations[i].strip() if i < len(locations) else ""
            location = raw_loc if raw_loc else s.get("location", "Egypt")
            jobs.append(Job(
                title=_match_title(title),
                company=company,
                location=location,
                url=f"https://www.linkedin.com/jobs/view/{job_id}/" if job_id else base,
                source="linkedin_posts",
                original_source=f"LinkedIn HR � {s.get('keywords', '')}",
                tags=["linkedin", "hr-search", s.get("location", "").split(",")[0].lower()],
                is_remote=False,
            ))
        time.sleep(random.uniform(2, 3.5))

    log.info(f"LinkedIn HR Search: {len(jobs)} jobs")
    return jobs


def fetch_linkedin_posts():
    """Aggregate LinkedIn post-based hiring signals."""
    all_jobs = []
    try:
        all_jobs.extend(_fetch_via_linkedin_search_api())
    except Exception as e:
        log.warning(f"linkedin_posts _fetch_via_linkedin_search_api failed: {e}")
    log.info(f"LinkedIn Posts total: {len(all_jobs)} jobs")
    return all_jobs
