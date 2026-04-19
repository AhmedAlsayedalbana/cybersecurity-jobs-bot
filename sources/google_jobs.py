"""
Google Jobs — SerpAPI + Wuzzuf HTML fallback.
v31: Fixed duplicate code, added more Egyptian searches, added Wuzzuf direct scrape.
"""

import logging
import re
import os
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
}

GOOGLE_JOBS_SEARCHES = [
    # Egypt — broad + specific roles
    {"q": "cybersecurity jobs Egypt",              "location": "Egypt",                        "gl": "eg"},
    {"q": "SOC analyst jobs Cairo Egypt",          "location": "Cairo, Egypt",                 "gl": "eg"},
    {"q": "penetration tester jobs Egypt",         "location": "Egypt",                        "gl": "eg"},
    {"q": "security engineer jobs Egypt",          "location": "Egypt",                        "gl": "eg"},
    {"q": "junior cybersecurity jobs Egypt",       "location": "Egypt",                        "gl": "eg"},
    {"q": "information security analyst Egypt",    "location": "Egypt",                        "gl": "eg"},
    {"q": "GRC analyst jobs Egypt",                "location": "Egypt",                        "gl": "eg"},
    {"q": "network security engineer Cairo",       "location": "Cairo, Egypt",                 "gl": "eg"},
    {"q": "cloud security engineer Egypt",         "location": "Egypt",                        "gl": "eg"},
    {"q": "DFIR analyst Egypt",                    "location": "Egypt",                        "gl": "eg"},
    {"q": "security analyst Alexandria Egypt",     "location": "Alexandria, Egypt",            "gl": "eg"},
    {"q": "وظائف أمن معلومات مصر",                "location": "Egypt",                        "gl": "eg"},
    {"q": "وظائف أمن سيبراني القاهرة",            "location": "Cairo, Egypt",                 "gl": "eg"},
    {"q": "cybersecurity New Administrative Capital", "location": "Egypt",                     "gl": "eg"},
    {"q": "cybersecurity Smart Village Egypt",     "location": "Egypt",                        "gl": "eg"},
    # Saudi Arabia
    {"q": "cybersecurity jobs Saudi Arabia",       "location": "Riyadh, Saudi Arabia",         "gl": "sa"},
    {"q": "SOC analyst Riyadh",                    "location": "Riyadh, Saudi Arabia",         "gl": "sa"},
    {"q": "security engineer Jeddah",              "location": "Jeddah, Saudi Arabia",         "gl": "sa"},
    {"q": "وظائف أمن سيبراني السعودية",            "location": "Riyadh, Saudi Arabia",         "gl": "sa"},
    # UAE
    {"q": "cybersecurity jobs Dubai",              "location": "Dubai, United Arab Emirates",  "gl": "ae"},
    {"q": "security analyst Abu Dhabi",            "location": "Abu Dhabi, United Arab Emirates", "gl": "ae"},
    {"q": "SOC analyst UAE",                       "location": "Dubai, United Arab Emirates",  "gl": "ae"},
    # Other Gulf
    {"q": "cybersecurity jobs Qatar",              "location": "Doha, Qatar",                  "gl": "qa"},
    {"q": "security engineer Kuwait",              "location": "Kuwait City, Kuwait",          "gl": "kw"},
]


def _fetch_via_serpapi():
    if not SERPAPI_KEY:
        return []
    jobs = []
    seen_urls = set()
    _first_done = False
    for search in GOOGLE_JOBS_SEARCHES:
        params = {
            "engine":   "google_jobs",
            "q":        search["q"],
            "location": search.get("location", ""),
            "api_key":  SERPAPI_KEY,
            "hl":       "en",
            "gl":       search.get("gl", "us"),
        }
        data = get_json("https://serpapi.com/search", params=params, headers=HEADERS)
        if not _first_done:
            _first_done = True
            if not data or "jobs_results" not in data:
                log.warning("SerpAPI: first request failed — skipping remaining")
                break
        if not data or "jobs_results" not in data:
            continue
        for item in data["jobs_results"]:
            url_job = ""
            for link in item.get("related_links", []):
                url_job = link.get("link", "")
                if url_job:
                    break
            if not url_job:
                url_job = ("https://www.google.com/search?q="
                           + search["q"].replace(" ", "+") + "&ibp=htl;jobs")
            if url_job in seen_urls:
                continue
            seen_urls.add(url_job)
            jobs.append(Job(
                title=item.get("title", ""),
                company=item.get("company_name", "Unknown"),
                location=item.get("location", search.get("location", "")),
                url=url_job,
                source="google_jobs",
                description=(item.get("description") or "")[:300],
                tags=["google_jobs", search.get("gl", "")],
                is_remote="remote" in item.get("title", "").lower(),
            ))
    log.info(f"Google Jobs (SerpAPI): {len(jobs)} jobs")
    return jobs


def _fetch_wuzzuf_direct():
    """
    Wuzzuf.net direct scrape — Egypt's #1 job board.
    Catches roles not indexed by SerpAPI.
    """
    jobs = []
    seen = set()
    queries = [
        ("cybersecurity", "cybersecurity"),
        ("information-security", "information security"),
        ("soc-analyst", "SOC analyst"),
        ("security-engineer", "security engineer"),
        ("penetration-testing", "penetration testing"),
        ("network-security", "network security"),
        ("grc-compliance", "GRC compliance"),
    ]
    for slug, label in queries:
        url = f"https://wuzzuf.net/search/jobs/?q={slug}&a=navbl"
        html = get_text(url, headers=HEADERS)
        if not html:
            continue
        # Extract job cards via JSON-LD
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                import json
                data = json.loads(block.strip())
                if not isinstance(data, dict):
                    continue
                if data.get("@type") != "JobPosting":
                    continue
                title = (data.get("title") or "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                hiring = data.get("hiringOrganization") or {}
                company = hiring.get("name", "Unknown") if isinstance(hiring, dict) else "Unknown"
                addr = data.get("jobLocation", {})
                if isinstance(addr, list):
                    addr = addr[0] if addr else {}
                loc_obj = addr.get("address", {}) if isinstance(addr, dict) else {}
                location = loc_obj.get("addressLocality", "Egypt") if isinstance(loc_obj, dict) else "Egypt"
                jobs.append(Job(
                    title=title, company=company,
                    location=location or "Egypt",
                    url=data.get("url", url),
                    source="wuzzuf",
                    tags=["wuzzuf", "egypt"],
                    description=(data.get("description") or "")[:300],
                ))
            except Exception:
                continue
        # Also try simple title extraction as fallback
        titles_raw = re.findall(
            r'<h2[^>]*class="[^"]*css-m604qf[^"]*"[^>]*>\s*<a[^>]*>([^<]+)</a>',
            html
        )
        companies_raw = re.findall(
            r'<a[^>]*class="[^"]*css-17s97q8[^"]*"[^>]*>([^<]+)</a>',
            html
        )
        links_raw = re.findall(r'href="(https://wuzzuf\.net/jobs/p/[^"]+)"', html)
        for i, title in enumerate(titles_raw):
            title = title.strip()
            if not title or title in seen:
                continue
            seen.add(title)
            company = companies_raw[i].strip() if i < len(companies_raw) else "Unknown"
            url_j = links_raw[i] if i < len(links_raw) else url
            jobs.append(Job(
                title=title, company=company,
                location="Egypt",
                url=url_j,
                source="wuzzuf",
                tags=["wuzzuf", "egypt"],
            ))

    log.info(f"Wuzzuf direct: {len(jobs)} jobs")
    return jobs


def _fetch_forasna_direct():
    """Forasna.com — another major Egyptian jobs board."""
    jobs = []
    seen = set()
    queries = ["cybersecurity", "information-security", "soc-analyst", "security-engineer"]
    for q in queries:
        url = f"https://www.forasna.com/jobs?q={q}&location=egypt"
        html = get_text(url, headers=HEADERS)
        if not html:
            continue
        titles = re.findall(r'<h3[^>]*class="[^"]*job[^"]*title[^"]*"[^>]*>([^<]+)', html, re.IGNORECASE)
        companies = re.findall(r'<span[^>]*class="[^"]*company[^"]*"[^>]*>([^<]+)', html, re.IGNORECASE)
        links = re.findall(r'href="(https://www\.forasna\.com/jobs/[^"]+)"', html)
        for i, title in enumerate(titles):
            title = title.strip()
            if not title or title in seen:
                continue
            seen.add(title)
            jobs.append(Job(
                title=title,
                company=companies[i].strip() if i < len(companies) else "Unknown",
                location="Egypt",
                url=links[i] if i < len(links) else url,
                source="forasna",
                tags=["forasna", "egypt"],
            ))
    log.info(f"Forasna direct: {len(jobs)} jobs")
    return jobs


def _fetch_adzuna_mena():
    from config import ADZUNA_APP_ID, ADZUNA_APP_KEY
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return []
    jobs = []
    searches = [
        ("eg", "cybersecurity",       "Egypt"),
        ("eg", "SOC analyst",         "Egypt"),
        ("eg", "penetration tester",  "Egypt"),
        ("eg", "security engineer",   "Egypt"),
        ("ae", "cybersecurity",       "UAE"),
        ("ae", "security engineer",   "UAE"),
        ("ae", "SOC analyst",         "UAE"),
    ]
    for country_code, query, location in searches:
        url = (
            f"https://api.adzuna.com/v1/api/jobs/{country_code}/search/1"
            f"?app_id={ADZUNA_APP_ID}&app_key={ADZUNA_APP_KEY}"
            f"&results_per_page=20&what={query.replace(' ', '+')}&sort_by=date"
        )
        data = get_json(url, headers=HEADERS)
        if not data or "results" not in data:
            continue
        for item in data["results"]:
            jobs.append(Job(
                title=item.get("title", ""),
                company=item.get("company", {}).get("display_name", "Unknown"),
                location=item.get("location", {}).get("display_name", location),
                url=item.get("redirect_url", ""),
                source="adzuna_mena",
                tags=["adzuna", location],
                is_remote="remote" in item.get("title", "").lower(),
            ))
    log.info(f"Adzuna MENA: {len(jobs)} jobs")
    return jobs


def fetch_google_jobs():
    """Aggregate all Google/jobs sources."""
    all_jobs = []
    for fn in [_fetch_via_serpapi, _fetch_wuzzuf_direct, _fetch_forasna_direct, _fetch_adzuna_mena]:
        try:
            all_jobs.extend(fn())
        except Exception as e:
            log.warning(f"google_jobs sub-fetcher {fn.__name__} failed: {e}")
    return all_jobs
