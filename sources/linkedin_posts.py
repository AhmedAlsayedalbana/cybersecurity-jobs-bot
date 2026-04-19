"""
LinkedIn Posts Scraper — v31
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


# Google cache search — finds LinkedIn posts indexed by Google
def _fetch_via_google_cache():
    """
    Use Google search to find LinkedIn posts with #hiring + cybersecurity.
    Google indexes LinkedIn posts, so this catches HR posts that aren't in job listings.
    """
    jobs = []
    seen = set()

    queries = [
        'site:linkedin.com "#hiring" "cybersecurity" "Egypt"',
        'site:linkedin.com "#hiring" "SOC analyst" "Egypt"',
        'site:linkedin.com "#hiring" "information security" "Cairo"',
        'site:linkedin.com "#hiring" "security engineer" "Egypt"',
        'site:linkedin.com "#hiring" "penetration" "Egypt"',
        'site:linkedin.com "we are hiring" "cybersecurity" "Egypt"',
        'site:linkedin.com "نحن نوظف" "أمن" "مصر"',
        'site:linkedin.com "#hiring" "cybersecurity" "Saudi Arabia"',
        'site:linkedin.com "#hiring" "SOC" "Riyadh"',
        'site:linkedin.com "#hiring" "security" "Dubai"',
    ]

    for q in queries:
        encoded = urllib.parse.quote_plus(q)
        url = f"https://www.google.com/search?q={encoded}&num=10&tbs=qdr:w"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        html = get_text(url, headers=headers)
        if not html:
            time.sleep(2)
            continue

        # Extract LinkedIn post/profile URLs from Google results
        li_urls = re.findall(
            r'https://www\.linkedin\.com/(?:posts|pulse|feed/update)/[^\s"&<>]+',
            html
        )
        # Extract snippets with job info
        snippets = re.findall(r'<div[^>]*class="[^"]*VwiC3b[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)

        for snippet in snippets:
            clean = re.sub(r'<[^>]+>', ' ', snippet).strip()
            if not clean or len(clean) < 20:
                continue
            # Try to extract a job title from the snippet
            title_match = re.search(
                r'(?:hiring|looking for|seeking|vacancy|role|position|open)[:\s]+([A-Z][^.!?]{5,60})',
                clean, re.IGNORECASE
            )
            if not title_match:
                # Try to match known roles
                matched = _match_title(clean)
                if matched == clean.strip().title():  # no match
                    continue
                title = matched
            else:
                title = title_match.group(1).strip()

            if title in seen:
                continue

            # Determine location from query
            location = "Egypt"
            if "saudi" in q.lower() or "riyadh" in q.lower():
                location = "Saudi Arabia"
            elif "dubai" in q.lower():
                location = "UAE"

            seen.add(title)
            url_job = li_urls[0] if li_urls else f"https://www.linkedin.com/search/results/content/?keywords={urllib.parse.quote(q)}"
            jobs.append(Job(
                title=_match_title(title),
                company="Unknown",
                location=location,
                url=url_job,
                source="linkedin_hiring",
                original_source=f"#Hiring — {title}",
                description=clean[:300],
                tags=["#hiring", "linkedin", "hiring-post", "google-indexed"],
                is_remote=False,
            ))
        time.sleep(random.uniform(3, 5))  # respect Google rate limits

    log.info(f"LinkedIn Posts (Google cache): {len(jobs)} jobs")
    return jobs


def _fetch_via_linkedin_search_api():
    """
    LinkedIn jobs search — searches with keywords that HR use in job posts.
    Unlike regular job search, uses keywords that appear in LinkedIn posts.
    """
    from sources.http_utils import get_text as _get
    jobs = []
    seen = set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

    # HR-specific search terms — these match how HR write #hiring posts
    searches = [
        {"keywords": "we are hiring cybersecurity",     "location": "Egypt",  "f_TPR": "r604800"},
        {"keywords": "hiring now security analyst",      "location": "Egypt",  "f_TPR": "r604800"},
        {"keywords": "join our team cyber",              "location": "Egypt",  "f_TPR": "r604800"},
        {"keywords": "open position security engineer",  "location": "Egypt",  "f_TPR": "r604800"},
        {"keywords": "vacancy information security",     "location": "Egypt",  "f_TPR": "r604800"},
        {"keywords": "فرصة عمل أمن سيبراني",            "location": "Egypt",  "f_TPR": "r604800"},
        {"keywords": "مطلوب محلل أمن",                  "location": "Egypt",  "f_TPR": "r604800"},
        {"keywords": "we are hiring cybersecurity",      "location": "Saudi Arabia", "f_TPR": "r604800"},
        {"keywords": "hiring SOC analyst",               "location": "Saudi Arabia", "f_TPR": "r604800"},
        {"keywords": "نوظف أمن معلومات",                 "location": "Saudi Arabia", "f_TPR": "r604800"},
    ]

    for s in searches:
        params = {k: v for k, v in s.items()}
        params.update({"start": "0", "count": "10"})
        html = _get(base, params=params)
        if not html or len(html) < 200:
            time.sleep(3)
            continue

        job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        titles  = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', html)
        companies = re.findall(r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>\s*<a[^>]*>([^<]+)', html)

        for i, title in enumerate(titles):
            title = title.strip()
            if not title or title in seen:
                continue
            seen.add(title)
            job_id = job_ids[i] if i < len(job_ids) else ""
            company = companies[i].strip() if i < len(companies) else "Unknown"
            location = s.get("location", "Egypt")
            jobs.append(Job(
                title=_match_title(title),
                company=company,
                location=location,
                url=f"https://www.linkedin.com/jobs/view/{job_id}/" if job_id else base,
                source="linkedin_hiring",
                original_source=f"#Hiring — {title}",
                tags=["#hiring", "linkedin", "hiring-post"],
                is_remote=False,
            ))
        time.sleep(random.uniform(2, 3.5))

    log.info(f"LinkedIn HR Search: {len(jobs)} jobs")
    return jobs


def fetch_linkedin_posts():
    """Aggregate LinkedIn post-based hiring signals."""
    all_jobs = []
    for fn in [_fetch_via_linkedin_search_api, _fetch_via_google_cache]:
        try:
            all_jobs.extend(fn())
        except Exception as e:
            log.warning(f"linkedin_posts sub-fetcher {fn.__name__} failed: {e}")
    log.info(f"LinkedIn Posts total: {len(all_jobs)} jobs")
    return all_jobs
