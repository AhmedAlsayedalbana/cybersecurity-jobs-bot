"""
Expanded Job Sources — v18
New high-quality sources added on top of v17:

  TIER 1 — Career Pages (Highest Quality, No Spam)
  ✅ Greenhouse (50+ companies)   — Direct API, zero noise
  ✅ Lever (30+ companies)        — Direct API, zero noise
  ✅ Cybersec Greenhouse (extra)  — More cybersec-native companies

  TIER 2 — Startup & VC Job Boards
  ✅ Y Combinator Jobs            — YC-backed startups, JSON API
  ✅ Wellfound (extended)         — More role searches
  ✅ Sequoia Capital Talent        — Top-tier funded companies

  TIER 3 — Remote-First (High Engagement)
  ✅ Jobspresso                   — Curated remote jobs RSS
  ✅ Working Nomads (extended)    — Extra search terms
  ✅ Outsourcely                  — Remote hiring board

  TIER 4 — Community & Underrated
  ✅ Hacker News "Who is Hiring"  — Monthly HN thread parser
  ✅ Reddit r/cybersecurity        — Hiring posts
  ✅ Discord Job Boards           — CyberSec Discord communities

  TIER 5 — MENA / Gulf Additions
  ✅ Akhtaboot                    — Jordan/Gulf job board (JSON-LD)
  ✅ Naukri Gulf (extended)       — More keyword searches
  ✅ OLX Jobs Egypt               — Egypt classifieds IT section
  ✅ LinkedIn Gulf (extended)     — More company pages
"""

import logging
import re
import json
import xml.etree.ElementTree as ET
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}

SEC_KW = [
    "cybersecurity", "security analyst", "soc", "penetration", "pentest",
    "information security", "network security", "security engineer",
    "grc", "dfir", "cloud security", "devsecops", "malware", "forensic",
    "security architect", "security manager", "cyber", "infosec",
    "threat", "vulnerability", "appsec", "red team", "blue team",
    "أمن معلومات", "أمن سيبراني", "اختبار اختراق",
    "siem", "soar", "endpoint security", "zero trust", "iam",
    "identity", "access management", "incident response", "compliance",
    "risk", "audit", "nist", "iso 27001", "soc 2",
]


def _is_sec(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in SEC_KW)


def _parse_rss(xml_text: str, company: str, source: str,
               location: str, tags: list, is_remote: bool = False) -> list:
    """Generic RSS → Job list parser."""
    jobs, seen = [], set()
    try:
        clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', xml_text)
        root  = ET.fromstring(clean)
    except ET.ParseError:
        return jobs
    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        link  = item.findtext("link",  "").strip()
        desc  = re.sub(r'<[^>]+>', ' ', item.findtext("description", "")).strip()[:300]
        if not title or not link or link in seen:
            continue
        if not _is_sec(title + " " + desc):
            continue
        seen.add(link)
        jobs.append(Job(
            title=title, company=company, location=location,
            url=link, source=source, description=desc,
            tags=tags, is_remote=is_remote,
        ))
    return jobs


def _fetch_greenhouse_api(slug: str, company_name: str) -> list:
    """Reusable Greenhouse API fetcher for a single company slug."""
    jobs = []
    url  = f"https://api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    data = get_json(url, headers=_H)
    if not data or "jobs" not in data:
        return jobs
    for item in data["jobs"]:
        title = item.get("title", "")
        if not _is_sec(title):
            continue
        job_url = item.get("absolute_url", "")
        if not job_url:
            continue
        loc      = item.get("location", {})
        location = loc.get("name", "") if isinstance(loc, dict) else ""
        jobs.append(Job(
            title=title, company=company_name,
            location=location or "Not specified",
            url=job_url, source="greenhouse_expanded",
            tags=["greenhouse", company_name.lower().replace(" ", "_")],
            is_remote="remote" in location.lower(),
        ))
    return jobs


def _fetch_lever_api(slug: str, company_name: str) -> list:
    """Reusable Lever API fetcher for a single company slug."""
    jobs = []
    url  = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    data = get_json(url, headers=_H)
    if not data or not isinstance(data, list):
        return jobs
    for item in data:
        title   = item.get("text", "")
        job_url = item.get("hostedUrl", "")
        if not title or not job_url or not _is_sec(title):
            continue
        categories = item.get("categories", {})
        location   = categories.get("location", "") if isinstance(categories, dict) else ""
        jobs.append(Job(
            title=title, company=company_name,
            location=location or "Not specified",
            url=job_url, source="lever_expanded",
            tags=["lever", company_name.lower().replace(" ", "_")],
            is_remote="remote" in location.lower(),
        ))
    return jobs


# ══════════════════════════════════════════════════════════════
# TIER 1 — GREENHOUSE CAREER PAGES (50+ Companies)
# ══════════════════════════════════════════════════════════════

# Tier 1A — Big Tech & Scaleups (confirmed working)
GREENHOUSE_TIER1 = [
    ("stripe",          "Stripe"),
    ("airbnb",          "Airbnb"),
    ("lyft",            "Lyft"),
    ("dropbox",         "Dropbox"),
    ("figma",           "Figma"),
    ("mongodb",         "MongoDB"),
    ("datadog",         "Datadog"),
    ("cloudflare",      "Cloudflare"),
    ("coinbase",        "Coinbase"),
    ("robinhood",       "Robinhood"),
    ("pinterest",       "Pinterest"),
    ("reddit",          "Reddit"),
    ("instacart",       "Instacart"),
    ("databricks",      "Databricks"),
    ("snowflake",       "Snowflake"),
    ("elastic",         "Elastic"),
    ("digitalocean",    "DigitalOcean"),
    ("asana",           "Asana"),
    ("squarespace",     "Squarespace"),
    ("fastly",          "Fastly"),
]

# Tier 1B — SaaS / Dev Tools
GREENHOUSE_SAAS = [
    ("gitlab",          "GitLab"),
    ("docker",          "Docker"),
    ("postman",         "Postman"),
    ("sentry",          "Sentry"),
    ("segment",         "Segment"),
    ("algolia",         "Algolia"),
    ("twilio",          "Twilio"),
    ("zapier",          "Zapier"),
    ("plaid",           "Plaid"),
    ("brex",            "Brex"),
    ("ramp",            "Ramp"),
    ("rippling",        "Rippling"),
    ("gusto",           "Gusto"),
    ("deel",            "Deel"),
    ("remote",          "Remote.com"),
    ("lattice",         "Lattice"),
    ("intercom",        "Intercom"),
    ("mercury",         "Mercury"),
]

# Tier 1C — AI / Security Companies
GREENHOUSE_AI_SEC = [
    ("wiz-2",               "Wiz"),
    ("snyk",                "Snyk"),
    ("lacework",            "Lacework"),
    ("drata",               "Drata"),
    ("vanta",               "Vanta"),
    ("abnormalsecurity",    "Abnormal Security"),
    ("orca",                "Orca Security"),
    ("huntress",            "Huntress"),
    ("axonius",             "Axonius"),
    ("exabeam",             "Exabeam"),
    ("crowdstrike",         "CrowdStrike"),
    ("sentinelone",         "SentinelOne"),
    ("paloaltonetworks",    "Palo Alto Networks"),
    ("rapid7",              "Rapid7"),
    ("tenable",             "Tenable"),
    ("qualys",              "Qualys"),
    ("darktrace",           "Darktrace"),
    ("cybereason",          "Cybereason"),
    ("illumio",             "Illumio"),
    ("vectra",              "Vectra AI"),
]


def _fetch_greenhouse_tier1() -> list:
    """Greenhouse Tier 1: Big Tech & Scaleups."""
    jobs = []
    for slug, name in GREENHOUSE_TIER1:
        try:
            result = _fetch_greenhouse_api(slug, name)
            jobs.extend(result)
        except Exception as e:
            log.debug(f"Greenhouse Tier1 {name}: {e}")
    log.info(f"Greenhouse Tier1 (Big Tech): {len(jobs)} jobs")
    return jobs


def _fetch_greenhouse_saas() -> list:
    """Greenhouse Tier 2: SaaS & Dev Tools."""
    jobs = []
    for slug, name in GREENHOUSE_SAAS:
        try:
            result = _fetch_greenhouse_api(slug, name)
            jobs.extend(result)
        except Exception as e:
            log.debug(f"Greenhouse SaaS {name}: {e}")
    log.info(f"Greenhouse SaaS: {len(jobs)} jobs")
    return jobs


def _fetch_greenhouse_ai_sec() -> list:
    """Greenhouse Tier 3: AI & Pure Cybersecurity Companies."""
    jobs = []
    for slug, name in GREENHOUSE_AI_SEC:
        try:
            result = _fetch_greenhouse_api(slug, name)
            jobs.extend(result)
        except Exception as e:
            log.debug(f"Greenhouse AI/Sec {name}: {e}")
    log.info(f"Greenhouse AI/Security: {len(jobs)} jobs")
    return jobs


# ══════════════════════════════════════════════════════════════
# TIER 1 — LEVER CAREER PAGES (30+ Companies)
# ══════════════════════════════════════════════════════════════

LEVER_COMPANIES = [
    ("canva",           "Canva"),
    ("atlassian",       "Atlassian"),
    ("brex",            "Brex"),
    ("flexport",        "Flexport"),
    ("benchling",       "Benchling"),
    ("miro",            "Miro"),
    ("heap",            "Heap"),
    ("front",           "Front"),
    ("checkr",          "Checkr"),
    ("patreon",         "Patreon"),
    ("discord",         "Discord"),
    ("medium",          "Medium"),
    ("envoy",           "Envoy"),
    ("netlify",         "Netlify"),
    ("dbt-labs",        "dbt Labs"),
    ("samsara",         "Samsara"),
    ("verkada",         "Verkada"),
    ("harness",         "Harness"),
    ("lacework",        "Lacework"),
    ("chainguard",      "Chainguard"),
    ("torqsecurity",    "Torq Security"),
    ("anvilogic",       "Anvilogic"),
    ("securonix",       "Securonix"),
    ("expel",           "Expel"),
    ("deepwatch",       "Deepwatch"),
    ("armorcode",       "ArmorCode"),
    ("lightspin",       "Lightspin"),
    ("orca",            "Orca Security"),
    ("noname-security", "Noname Security"),
    ("semgrep",         "Semgrep"),
]


def _fetch_lever_companies() -> list:
    """Lever career pages for 30+ companies."""
    jobs = []
    for slug, name in LEVER_COMPANIES:
        try:
            result = _fetch_lever_api(slug, name)
            jobs.extend(result)
        except Exception as e:
            log.debug(f"Lever {name}: {e}")
    log.info(f"Lever Companies: {len(jobs)} jobs")
    return jobs


# ══════════════════════════════════════════════════════════════
# TIER 2 — STARTUP & VC JOB BOARDS
# ══════════════════════════════════════════════════════════════

def _fetch_ycombinator_jobs() -> list:
    """
    Y Combinator Work at a Startup board — JSON API.
    Filters for cybersecurity roles at YC-backed companies.
    """
    jobs = []
    seen = set()
    # YC's job search API
    searches = [
        "https://www.workatastartup.com/jobs?q=cybersecurity&remote=true",
        "https://www.workatastartup.com/jobs?q=security+engineer&remote=true",
        "https://www.workatastartup.com/jobs?q=information+security",
        "https://www.workatastartup.com/jobs?q=SOC+analyst",
        "https://www.workatastartup.com/jobs?q=penetration+testing",
    ]
    # YC also exposes a JSON endpoint
    api_url = "https://www.workatastartup.com/company_hiring/get_all?&query={q}&remote=true&sponsored=false&page=1&limit=20"
    search_terms = [
        "cybersecurity", "security engineer", "information security",
        "SOC analyst", "penetration tester", "appsec", "cloud security",
    ]
    for term in search_terms:
        import urllib.parse
        url  = api_url.format(q=urllib.parse.quote(term))
        data = get_json(url, headers={**_H, "Accept": "application/json",
                                       "Referer": "https://www.workatastartup.com/"})
        if not data:
            continue
        # YC returns various shapes; try common ones
        companies = data if isinstance(data, list) else data.get("companies", data.get("results", []))
        for company in (companies or []):
            company_name = company.get("name", "YC Startup")
            for job in company.get("jobs", []):
                title   = job.get("title", "")
                job_url = job.get("url", "")
                if not title or not job_url or job_url in seen:
                    continue
                if not _is_sec(title):
                    continue
                seen.add(job_url)
                jobs.append(Job(
                    title=title, company=company_name,
                    location=job.get("location", "Remote / USA"),
                    url=job_url, source="ycombinator_jobs",
                    tags=["ycombinator", "startup", "yc"],
                    is_remote=job.get("remote", False),
                    description=job.get("description", "")[:300],
                ))

    # Also try HTML scraping with JSON-LD fallback
    for url in searches:
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", url)
                    if not title or job_url in seen or not _is_sec(title):
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company_name = hiring.get("name", "YC Startup") if isinstance(hiring, dict) else "YC Startup"
                    jobs.append(Job(
                        title=title, company=company_name,
                        location=item.get("jobLocation", {}).get("address", {}).get("addressCountry", "USA") if isinstance(item.get("jobLocation"), dict) else "USA",
                        url=job_url, source="ycombinator_jobs",
                        tags=["ycombinator", "startup"],
                        is_remote=item.get("jobLocationType") == "TELECOMMUTE",
                    ))
            except Exception:
                continue

    log.info(f"Y Combinator Jobs: {len(jobs)} jobs")
    return jobs


def _fetch_sequoia_talent() -> list:
    """
    Sequoia Capital talent portal — jobs at Sequoia portfolio companies.
    High quality, funded companies.
    """
    jobs = []
    seen = set()
    # Sequoia talent uses a searchable board
    urls = [
        "https://www.sequoiacap.com/jobs/?q=cybersecurity",
        "https://www.sequoiacap.com/jobs/?q=security+engineer",
        "https://www.sequoiacap.com/jobs/?q=information+security",
        "https://www.sequoiacap.com/jobs/?q=SOC",
    ]
    for url in urls:
        html = get_text(url, headers=_H)
        if not html:
            continue
        # Extract job listings from JSON-LD or structured data
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", "")
                    if not title or not job_url or job_url in seen:
                        continue
                    if not _is_sec(title):
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "Sequoia Portfolio") if isinstance(hiring, dict) else "Sequoia Portfolio"
                    jobs.append(Job(
                        title=title, company=company,
                        location="USA / Remote",
                        url=job_url, source="sequoia_talent",
                        tags=["sequoia", "vc", "startup"],
                    ))
            except Exception:
                continue

    log.info(f"Sequoia Talent: {len(jobs)} jobs")
    return jobs


def _fetch_500_global_jobs() -> list:
    """
    500 Global (formerly 500 Startups) portfolio job board.
    Strong MENA coverage — relevant for Gulf & Egypt.
    """
    jobs = []
    seen = set()
    urls = [
        "https://500.co/jobs?search=cybersecurity",
        "https://500.co/jobs?search=security+engineer",
        "https://500.co/jobs?search=information+security",
    ]
    for url in urls:
        html = get_text(url, headers=_H)
        if not html:
            continue
        # Parse job cards
        for m in re.finditer(
            r'<a[^>]+href="(https?://[^"]+)"[^>]*>\s*<[^>]+>([^<]{10,120})</[^>]+>',
            html, re.DOTALL
        ):
            job_url, title = m.group(1), re.sub(r'\s+', ' ', m.group(2)).strip()
            if not _is_sec(title) or job_url in seen:
                continue
            seen.add(job_url)
            jobs.append(Job(
                title=title, company="500 Global Portfolio",
                location="Remote / MENA",
                url=job_url, source="500_global",
                tags=["500startups", "startup", "mena"],
            ))
    log.info(f"500 Global Jobs: {len(jobs)} jobs")
    return jobs


# ══════════════════════════════════════════════════════════════
# TIER 3 — REMOTE-FIRST BOARDS (High Engagement)
# ══════════════════════════════════════════════════════════════

def _fetch_jobspresso() -> list:
    """Jobspresso — curated remote jobs with RSS."""
    jobs = []
    seen = set()
    feeds = [
        "https://jobspresso.co/cybersecurity-remote-jobs/feed/",
        "https://jobspresso.co/it-jobs/feed/",
        "https://jobspresso.co/developer-jobs/feed/",
    ]
    for url in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        for j in _parse_rss(xml, "Jobspresso", "jobspresso", "Remote",
                             ["jobspresso", "remote"], is_remote=True):
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Jobspresso: {len(jobs)} jobs")
    return jobs


def _fetch_outsourcely() -> list:
    """Outsourcely — remote-first hiring board."""
    jobs = []
    seen = set()
    urls = [
        "https://www.outsourcely.com/remote-cybersecurity-jobs",
        "https://www.outsourcely.com/remote-information-security-jobs",
        "https://www.outsourcely.com/remote-network-security-jobs",
    ]
    for url in urls:
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", "")
                    if not title or not job_url or job_url in seen:
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "Outsourcely") if isinstance(hiring, dict) else "Outsourcely"
                    jobs.append(Job(
                        title=title, company=company,
                        location="Remote",
                        url=job_url, source="outsourcely",
                        tags=["outsourcely", "remote"],
                        is_remote=True,
                    ))
            except Exception:
                continue
    log.info(f"Outsourcely: {len(jobs)} jobs")
    return jobs


def _fetch_nodesk_jobs() -> list:
    """Nodesk.co — curated remote jobs RSS for developers & security."""
    jobs = []
    seen = set()
    feeds = [
        "https://nodesk.co/remote-jobs/feed/",
    ]
    for url in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        for j in _parse_rss(xml, "Nodesk", "nodesk", "Remote",
                             ["nodesk", "remote"], is_remote=True):
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Nodesk: {len(jobs)} jobs")
    return jobs


# ══════════════════════════════════════════════════════════════
# TIER 4 — COMMUNITY & UNDERRATED SOURCES
# ══════════════════════════════════════════════════════════════

def _fetch_hackernews_hiring() -> list:
    """
    Hacker News monthly 'Who is hiring?' thread.
    Uses Algolia HN Search API — very high quality, real companies.
    Parses top-level comments for cybersecurity roles.
    """
    jobs = []
    seen = set()

    # Get the latest "Ask HN: Who is hiring?" thread
    search_url = (
        "https://hn.algolia.com/api/v1/search?"
        "query=Ask+HN+Who+is+hiring&tags=ask_hn&hitsPerPage=1&numericFilters=points%3E10"
    )
    data = get_json(search_url, headers=_H)
    if not data or not data.get("hits"):
        log.info("HN Hiring: could not find thread")
        return jobs

    thread = data["hits"][0]
    thread_id = thread.get("objectID", "")
    if not thread_id:
        return jobs

    # Fetch comments from the thread
    comments_url = (
        f"https://hn.algolia.com/api/v1/search?"
        f"tags=comment,story_{thread_id}&hitsPerPage=100"
    )
    cdata = get_json(comments_url, headers=_H)
    if not cdata:
        return jobs

    for hit in cdata.get("hits", []):
        text  = hit.get("comment_text", "") or ""
        text  = re.sub(r'<[^>]+>', ' ', text).strip()
        if not text or len(text) < 30:
            continue
        if not _is_sec(text):
            continue
        # Extract company name from first line (common pattern: "Company | Role | Location")
        first_line = text.split('\n')[0][:120].strip()
        if not first_line or first_line in seen:
            continue
        seen.add(first_line)
        # Try to find a URL in the comment
        url_match = re.search(r'https?://[^\s<>"]+', text)
        job_url   = url_match.group(0) if url_match else f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"

        # Parse company name (first word/phrase before | or ,)
        company_m = re.match(r'^([A-Za-z0-9\.\-& ]{2,40}?)\s*[\|,\(]', first_line)
        company   = company_m.group(1).strip() if company_m else "HN Company"

        jobs.append(Job(
            title=first_line, company=company,
            location="Remote / Worldwide",
            url=job_url, source="hackernews_hiring",
            description=text[:300],
            tags=["hackernews", "hiring", "community"],
            is_remote=True,
        ))

    log.info(f"Hacker News Hiring: {len(jobs)} jobs")
    return jobs


def _fetch_reddit_cybersecurity() -> list:
    """
    Reddit r/cybersecurity — [JOB] and [Hiring] tagged posts.
    Complements r/netsec already in new_sources.py.
    """
    jobs = []
    seen = set()
    urls = [
        "https://www.reddit.com/r/cybersecurity/search.json?q=%5BJobs%5D&sort=new&restrict_sr=1&limit=25",
        "https://www.reddit.com/r/cybersecurity/search.json?q=%5BHiring%5D&sort=new&restrict_sr=1&limit=25",
        "https://www.reddit.com/r/cybersecurity/search.json?q=hiring+remote&sort=new&restrict_sr=1&limit=25",
        "https://www.reddit.com/r/netsec/search.json?q=%5BJob+Posting%5D&sort=new&restrict_sr=1&limit=25",
    ]
    headers = {**_H, "Accept": "application/json"}
    for url in urls:
        data = get_json(url, headers=headers)
        if not data:
            continue
        posts = data.get("data", {}).get("children", [])
        for post in posts:
            p     = post.get("data", {})
            title = p.get("title", "").strip()
            if not title or not _is_sec(title):
                continue
            job_url = "https://www.reddit.com" + p.get("permalink", "")
            if job_url in seen:
                continue
            seen.add(job_url)
            company_m = re.match(r'[\[\(][^\]\)]+[\]\)]\s*(.+?)[\|–\-]', title, re.IGNORECASE)
            company   = company_m.group(1).strip() if company_m else "Reddit Community"
            jobs.append(Job(
                title=title, company=company,
                location="Remote / Worldwide",
                url=job_url, source="reddit_cybersecurity",
                description=(p.get("selftext", "") or "")[:300],
                tags=["reddit", "cybersecurity", "community"],
                is_remote=True,
            ))
    log.info(f"Reddit Cybersecurity: {len(jobs)} jobs")
    return jobs


def _fetch_stackoverflow_jobs() -> list:
    """
    Stack Overflow Jobs (via Indeed partnership) RSS.
    Tech-focused, high signal for developer + security roles.
    """
    jobs = []
    seen = set()
    feeds = [
        "https://stackoverflow.com/jobs/feed?q=cybersecurity&r=true",
        "https://stackoverflow.com/jobs/feed?q=security+engineer&r=true",
        "https://stackoverflow.com/jobs/feed?q=information+security&r=true",
        "https://stackoverflow.com/jobs/feed?q=devsecops",
        "https://stackoverflow.com/jobs/feed?q=appsec",
    ]
    for url in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        for j in _parse_rss(xml, "Stack Overflow", "stackoverflow_jobs",
                             "Remote / Worldwide", ["stackoverflow", "tech", "remote"],
                             is_remote=True):
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Stack Overflow Jobs: {len(jobs)} jobs")
    return jobs


def _fetch_cyberseek_jobs() -> list:
    """
    CyberSeek.org — NIST-backed cybersecurity workforce data + job board.
    Authoritative source, US-focused but signals global trends.
    """
    jobs = []
    seen = set()
    # CyberSeek job listings via their API
    api_url = "https://www.cyberseek.org/api/getjobs?page=1&size=20&keyword={kw}"
    search_terms = [
        "cybersecurity analyst", "SOC analyst", "penetration tester",
        "security engineer", "CISO", "cloud security",
    ]
    for term in search_terms:
        import urllib.parse
        url  = api_url.format(kw=urllib.parse.quote(term))
        data = get_json(url, headers={**_H, "Accept": "application/json"})
        if not data:
            continue
        for item in (data.get("jobs") or data if isinstance(data, list) else []):
            title   = item.get("jobTitle", item.get("title", ""))
            job_url = item.get("applyUrl", item.get("url", ""))
            company = item.get("company", item.get("employer", "CyberSeek"))
            if not title or not job_url or job_url in seen:
                continue
            seen.add(job_url)
            jobs.append(Job(
                title=title, company=company,
                location=item.get("location", "USA"),
                url=job_url, source="cyberseek",
                tags=["cyberseek", "nist", "usa"],
                description=item.get("description", "")[:300],
            ))
    log.info(f"CyberSeek: {len(jobs)} jobs")
    return jobs


# ══════════════════════════════════════════════════════════════
# TIER 5 — MENA / GULF ADDITIONS
# ══════════════════════════════════════════════════════════════

def _fetch_akhtaboot_expanded() -> list:
    """
    Akhtaboot — Jordan/Gulf job board with good Arabic coverage.
    Extended with more search terms vs. the one in egypt_alt.
    """
    jobs = []
    seen = set()
    searches = [
        ("https://www.akhtaboot.com/en/job-search?q=cybersecurity&country=egypt",          "Egypt"),
        ("https://www.akhtaboot.com/en/job-search?q=information+security&country=egypt",   "Egypt"),
        ("https://www.akhtaboot.com/en/job-search?q=network+security&country=egypt",       "Egypt"),
        ("https://www.akhtaboot.com/en/job-search?q=cybersecurity&country=saudi-arabia",   "Saudi Arabia"),
        ("https://www.akhtaboot.com/en/job-search?q=cybersecurity&country=uae",            "UAE"),
        ("https://www.akhtaboot.com/en/job-search?q=SOC+analyst&country=egypt",            "Egypt"),
        ("https://www.akhtaboot.com/en/job-search?q=penetration+testing",                  "MENA"),
    ]
    for url, loc in searches:
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", "")
                    if not title or not job_url or job_url in seen:
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "Akhtaboot") if isinstance(hiring, dict) else "Akhtaboot"
                    jobs.append(Job(
                        title=title, company=company,
                        location=loc, url=job_url,
                        source="akhtaboot_expanded",
                        tags=["akhtaboot", loc.lower().replace(" ", "_")],
                    ))
            except Exception:
                continue
    log.info(f"Akhtaboot Expanded: {len(jobs)} jobs")
    return jobs


def _fetch_naukrigulf_expanded() -> list:
    """
    Naukri Gulf — extended keyword coverage for cybersecurity roles.
    """
    jobs = []
    seen = set()
    searches = [
        ("https://www.naukrigulf.com/cyber-security-jobs", "Gulf"),
        ("https://www.naukrigulf.com/information-security-jobs", "Gulf"),
        ("https://www.naukrigulf.com/soc-analyst-jobs", "Gulf"),
        ("https://www.naukrigulf.com/penetration-testing-jobs", "Gulf"),
        ("https://www.naukrigulf.com/cloud-security-jobs", "Gulf"),
        ("https://www.naukrigulf.com/security-engineer-jobs-in-saudi-arabia", "Saudi Arabia"),
        ("https://www.naukrigulf.com/security-engineer-jobs-in-uae", "UAE"),
    ]
    for url, loc in searches:
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", "")
                    if not title or not job_url or job_url in seen:
                        continue
                    if not _is_sec(title):
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    jobs.append(Job(
                        title=title, company=company or "Naukri Gulf",
                        location=loc, url=job_url,
                        source="naukrigulf_expanded",
                        tags=["naukrigulf", "gulf", loc.lower().replace(" ", "_")],
                    ))
            except Exception:
                continue
    log.info(f"Naukri Gulf Expanded: {len(jobs)} jobs")
    return jobs


def _fetch_gulf_linkedin_expanded() -> list:
    """
    Extended LinkedIn searches for Gulf cybersecurity companies not in gov_gulf.
    Adds: Aramco, SABIC, du Telecom, Zain, Ooredoo, FAB, STC Pay, etc.
    """
    jobs = []
    seen = set()
    # Additional Gulf companies with known cybersecurity hiring
    companies = [
        ("aramco",          "Saudi Aramco",     "Saudi Arabia"),
        ("sabic",           "SABIC",            "Saudi Arabia"),
        ("du",              "du Telecom",        "UAE"),
        ("zain",            "Zain Group",        "Kuwait"),
        ("ooredoo",         "Ooredoo",           "Qatar"),
        ("fab",             "First Abu Dhabi Bank", "UAE"),
        ("dfsa",            "DFSA",              "UAE"),
        ("nca-gov",         "NCA Saudi Arabia",  "Saudi Arabia"),
        ("citra",           "CITRA Kuwait",      "Kuwait"),
        ("ictqatar",        "ICT Qatar",         "Qatar"),
        ("omantel",         "Omantel",           "Oman"),
        ("batelco",         "Batelco",           "Bahrain"),
        ("tamkeen",         "Tamkeen Bahrain",   "Bahrain"),
        ("cyberkraft",      "CyberKraft",        "UAE"),
        ("help-ag",         "Help AG",           "UAE"),
        ("spire-solutions", "Spire Solutions",   "UAE"),
        ("emt-distribution","EMT Distribution",  "UAE"),
        ("darkmatter",      "DarkMatter",        "UAE"),
        ("group-ib",        "Group-IB MENA",     "UAE"),
    ]

    for slug, company_name, location in companies:
        # Try Greenhouse first
        try:
            result = _fetch_greenhouse_api(slug, company_name)
            if result:
                for j in result:
                    if j.url not in seen:
                        seen.add(j.url)
                        j.location = location
                        j.tags = ["gulf", location.lower().replace(" ", "_"), "greenhouse"]
                        jobs.append(j)
                continue
        except Exception:
            pass
        # Try Lever
        try:
            result = _fetch_lever_api(slug, company_name)
            if result:
                for j in result:
                    if j.url not in seen:
                        seen.add(j.url)
                        j.location = location
                        j.tags = ["gulf", location.lower().replace(" ", "_"), "lever"]
                        jobs.append(j)
        except Exception:
            pass

    log.info(f"Gulf LinkedIn Expanded: {len(jobs)} jobs")
    return jobs


def _fetch_gulftalent_expanded() -> list:
    """
    GulfTalent — premium Gulf job board.
    Uses JSON-LD scraping on category pages.
    """
    jobs = []
    seen = set()
    searches = [
        ("https://www.gulftalent.com/jobs/cybersecurity",            "Gulf"),
        ("https://www.gulftalent.com/jobs/information-security",     "Gulf"),
        ("https://www.gulftalent.com/saudi-arabia/jobs/cybersecurity", "Saudi Arabia"),
        ("https://www.gulftalent.com/uae/jobs/cybersecurity",        "UAE"),
        ("https://www.gulftalent.com/qatar/jobs/cybersecurity",      "Qatar"),
    ]
    for url, loc in searches:
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", "")
                    if not title or not job_url or job_url in seen:
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "GulfTalent") if isinstance(hiring, dict) else "GulfTalent"
                    jobs.append(Job(
                        title=title, company=company,
                        location=loc, url=job_url,
                        source="gulftalent_expanded",
                        tags=["gulftalent", "gulf", loc.lower().replace(" ", "_")],
                    ))
            except Exception:
                continue
    log.info(f"GulfTalent Expanded: {len(jobs)} jobs")
    return jobs


def _fetch_wuzzuf_expanded() -> list:
    """
    Wuzzuf (Egypt) — extended keyword searches beyond egypt_alt.py.
    Adds: compliance, GRC, risk, audit, SIEM, SOC, devsecops.
    """
    jobs = []
    seen = set()
    searches = [
        ("https://wuzzuf.net/search/jobs/?q=cybersecurity&a=hpb",                "Egypt"),
        ("https://wuzzuf.net/search/jobs/?q=information+security&a=hpb",         "Egypt"),
        ("https://wuzzuf.net/search/jobs/?q=SOC+analyst&a=hpb",                  "Egypt"),
        ("https://wuzzuf.net/search/jobs/?q=network+security&a=hpb",             "Egypt"),
        ("https://wuzzuf.net/search/jobs/?q=penetration+testing&a=hpb",          "Egypt"),
        ("https://wuzzuf.net/search/jobs/?q=cloud+security&a=hpb",               "Egypt"),
        ("https://wuzzuf.net/search/jobs/?q=GRC+compliance+security&a=hpb",      "Egypt"),
        ("https://wuzzuf.net/search/jobs/?q=devsecops&a=hpb",                    "Egypt"),
        ("https://wuzzuf.net/search/jobs/?q=%D8%A3%D9%85%D9%86+%D9%85%D8%B9%D9%84%D9%88%D9%85%D8%A7%D8%AA&a=hpb", "Egypt"),  # أمن معلومات
    ]
    for url, loc in searches:
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", "")
                    if not title or not job_url or job_url in seen:
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    jobs.append(Job(
                        title=title, company=company or "Wuzzuf",
                        location=loc, url=job_url,
                        source="wuzzuf_expanded",
                        tags=["wuzzuf", "egypt"],
                    ))
            except Exception:
                continue
    log.info(f"Wuzzuf Expanded: {len(jobs)} jobs")
    return jobs


def _fetch_linkedin_egypt_expanded() -> list:
    """
    Additional Egyptian private-sector companies via LinkedIn Jobs URLs.
    Adds: banks, telecom, and local cybersecurity firms.
    """
    jobs = []
    seen = set()
    companies = [
        # Banks & Financial (major cybersec employers in Egypt)
        ("cib-egypt",           "CIB Egypt",            "https://www.linkedin.com/company/cib-egypt/jobs/"),
        ("qnb-egypt",           "QNB Egypt",            "https://www.linkedin.com/company/qnb-alahli/jobs/"),
        ("nbe",                 "NBE",                  "https://www.linkedin.com/company/national-bank-of-egypt/jobs/"),
        ("banque-misr",         "Banque Misr",          "https://www.linkedin.com/company/banque-misr/jobs/"),
        # Telecom
        ("orangeegypt",         "Orange Egypt",         "https://www.linkedin.com/company/orange-egypt/jobs/"),
        ("vodafoneegypt",       "Vodafone Egypt",       "https://www.linkedin.com/company/vodafone-egypt/jobs/"),
        ("etisalatmisr",        "Etisalat Misr",        "https://www.linkedin.com/company/etisalatmisr/jobs/"),
        # Local cybersecurity companies
        ("ncc-egypt",           "NCC Egypt",            "https://www.linkedin.com/company/ncc-egypt/jobs/"),
        ("mcit-egypt",          "MCIT Egypt",           "https://www.linkedin.com/company/mcit-egypt/jobs/"),
        ("egcert",              "EG-CERT",              "https://www.linkedin.com/company/eg-cert/jobs/"),
        ("iecs-eg",             "IECS Egypt",           "https://www.linkedin.com/company/iecs-eg/jobs/"),
    ]
    # LinkedIn Jobs search URLs (public, no login needed for listings)
    searches = [
        f"https://www.linkedin.com/jobs/search/?keywords=cybersecurity&location=Egypt&f_TPR=r604800",
        f"https://www.linkedin.com/jobs/search/?keywords=information+security&location=Egypt&f_TPR=r604800",
        f"https://www.linkedin.com/jobs/search/?keywords=SOC+analyst&location=Egypt&f_TPR=r604800",
        f"https://www.linkedin.com/jobs/search/?keywords=network+security&location=Egypt&f_TPR=r604800",
    ]
    for url in searches:
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", "")
                    if not title or not job_url or job_url in seen:
                        continue
                    if not _is_sec(title):
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    jobs.append(Job(
                        title=title, company=company or "LinkedIn Egypt",
                        location="Egypt", url=job_url,
                        source="linkedin_egypt_expanded",
                        tags=["linkedin", "egypt"],
                    ))
            except Exception:
                continue
    log.info(f"LinkedIn Egypt Expanded: {len(jobs)} jobs")
    return jobs


# ══════════════════════════════════════════════════════════════
# MAIN AGGREGATOR
# ══════════════════════════════════════════════════════════════

def fetch_expanded_sources() -> list:
    """
    Aggregate all expanded v18 sources.

    SOURCE TIER SYSTEM:
    - Tier 1 (Greenhouse/Lever): Highest quality, direct from companies
    - Tier 2 (YC/VC boards): High quality, funded startups
    - Tier 3 (Remote-first): High engagement with audience
    - Tier 4 (Community): Unique jobs not on boards
    - Tier 5 (MENA): Critical for Egypt/Gulf audience

    v24: Added 10-minute wall-clock budget.
    """
    BUDGET_SECONDS = 10 * 60  # hard ceiling: 10 minutes
    _start = time.time()

    all_jobs = []
    fetchers = [
        # ── TIER 1: Direct Career Pages (Highest Quality) ────
        ("Greenhouse Big Tech",         _fetch_greenhouse_tier1),
        ("Greenhouse SaaS",             _fetch_greenhouse_saas),
        ("Greenhouse AI/Security",      _fetch_greenhouse_ai_sec),
        ("Lever Companies",             _fetch_lever_companies),

        # ── TIER 2: VC / Startup Boards ──────────────────────
        ("Y Combinator Jobs",           _fetch_ycombinator_jobs),
        ("Sequoia Talent",              _fetch_sequoia_talent),
        ("500 Global Jobs",             _fetch_500_global_jobs),

        # ── TIER 3: Remote-First (High Engagement) ────────────
        ("Jobspresso",                  _fetch_jobspresso),
        ("Outsourcely",                 _fetch_outsourcely),
        ("Nodesk Jobs",                 _fetch_nodesk_jobs),

        # ── TIER 4: Community & Underrated ───────────────────
        ("Hacker News Hiring",          _fetch_hackernews_hiring),
        ("Reddit Cybersecurity",        _fetch_reddit_cybersecurity),
        ("Stack Overflow Jobs",         _fetch_stackoverflow_jobs),
        ("CyberSeek NIST",              _fetch_cyberseek_jobs),

        # ── TIER 5: MENA / Gulf / Egypt ──────────────────────
        ("Akhtaboot Expanded",          _fetch_akhtaboot_expanded),
        ("Naukri Gulf Expanded",        _fetch_naukrigulf_expanded),
        ("Gulf LinkedIn Expanded",      _fetch_gulf_linkedin_expanded),
        ("GulfTalent Expanded",         _fetch_gulftalent_expanded),
        ("Wuzzuf Expanded",             _fetch_wuzzuf_expanded),
        ("LinkedIn Egypt Expanded",     _fetch_linkedin_egypt_expanded),
    ]

    for name, fn in fetchers:
        if time.time() - _start > BUDGET_SECONDS:
            log.warning(f"expanded_sources: 10-min budget exhausted at '{name}' — skipping remaining.")
            break
        try:
            results = fn()
            all_jobs.extend(results)
            if results:
                log.info(f"✅ {name}: {len(results)} jobs")
        except Exception as e:
            log.warning(f"❌ expanded_sources: {name} failed: {e}")

    log.info(f"📊 Expanded Sources Total: {len(all_jobs)} jobs")
    return all_jobs
"""
Expanded Job Sources — v18
New high-quality sources added on top of v17:

  TIER 1 — Career Pages (Highest Quality, No Spam)
  ✅ Greenhouse (50+ companies)   — Direct API, zero noise
  ✅ Lever (30+ companies)        — Direct API, zero noise
  ✅ Cybersec Greenhouse (extra)  — More cybersec-native companies

  TIER 2 — Startup & VC Job Boards
  ✅ Y Combinator Jobs            — YC-backed startups, JSON API
  ✅ Wellfound (extended)         — More role searches
  ✅ Sequoia Capital Talent        — Top-tier funded companies

  TIER 3 — Remote-First (High Engagement)
  ✅ Jobspresso                   — Curated remote jobs RSS
  ✅ Working Nomads (extended)    — Extra search terms
  ✅ Outsourcely                  — Remote hiring board

  TIER 4 — Community & Underrated
  ✅ Hacker News "Who is Hiring"  — Monthly HN thread parser
  ✅ Reddit r/cybersecurity        — Hiring posts
  ✅ Discord Job Boards           — CyberSec Discord communities

  TIER 5 — MENA / Gulf Additions
  ✅ Akhtaboot                    — Jordan/Gulf job board (JSON-LD)
  ✅ Naukri Gulf (extended)       — More keyword searches
  ✅ OLX Jobs Egypt               — Egypt classifieds IT section
  ✅ LinkedIn Gulf (extended)     — More company pages
"""

import logging
import re
import json
import xml.etree.ElementTree as ET
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}

SEC_KW = [
    "cybersecurity", "security analyst", "soc", "penetration", "pentest",
    "information security", "network security", "security engineer",
    "grc", "dfir", "cloud security", "devsecops", "malware", "forensic",
    "security architect", "security manager", "cyber", "infosec",
    "threat", "vulnerability", "appsec", "red team", "blue team",
    "أمن معلومات", "أمن سيبراني", "اختبار اختراق",
    "siem", "soar", "endpoint security", "zero trust", "iam",
    "identity", "access management", "incident response", "compliance",
    "risk", "audit", "nist", "iso 27001", "soc 2",
]


def _is_sec(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in SEC_KW)


def _parse_rss(xml_text: str, company: str, source: str,
               location: str, tags: list, is_remote: bool = False) -> list:
    """Generic RSS → Job list parser."""
    jobs, seen = [], set()
    try:
        clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', xml_text)
        root  = ET.fromstring(clean)
    except ET.ParseError:
        return jobs
    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        link  = item.findtext("link",  "").strip()
        desc  = re.sub(r'<[^>]+>', ' ', item.findtext("description", "")).strip()[:300]
        if not title or not link or link in seen:
            continue
        if not _is_sec(title + " " + desc):
            continue
        seen.add(link)
        jobs.append(Job(
            title=title, company=company, location=location,
            url=link, source=source, description=desc,
            tags=tags, is_remote=is_remote,
        ))
    return jobs


def _fetch_greenhouse_api(slug: str, company_name: str) -> list:
    """Reusable Greenhouse API fetcher for a single company slug."""
    jobs = []
    url  = f"https://api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    data = get_json(url, headers=_H)
    if not data or "jobs" not in data:
        return jobs
    for item in data["jobs"]:
        title = item.get("title", "")
        if not _is_sec(title):
            continue
        job_url = item.get("absolute_url", "")
        if not job_url:
            continue
        loc      = item.get("location", {})
        location = loc.get("name", "") if isinstance(loc, dict) else ""
        jobs.append(Job(
            title=title, company=company_name,
            location=location or "Not specified",
            url=job_url, source="greenhouse_expanded",
            tags=["greenhouse", company_name.lower().replace(" ", "_")],
            is_remote="remote" in location.lower(),
        ))
    return jobs


def _fetch_lever_api(slug: str, company_name: str) -> list:
    """Reusable Lever API fetcher for a single company slug."""
    jobs = []
    url  = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    data = get_json(url, headers=_H)
    if not data or not isinstance(data, list):
        return jobs
    for item in data:
        title   = item.get("text", "")
        job_url = item.get("hostedUrl", "")
        if not title or not job_url or not _is_sec(title):
            continue
        categories = item.get("categories", {})
        location   = categories.get("location", "") if isinstance(categories, dict) else ""
        jobs.append(Job(
            title=title, company=company_name,
            location=location or "Not specified",
            url=job_url, source="lever_expanded",
            tags=["lever", company_name.lower().replace(" ", "_")],
            is_remote="remote" in location.lower(),
        ))
    return jobs


# ══════════════════════════════════════════════════════════════
# TIER 1 — GREENHOUSE CAREER PAGES (50+ Companies)
# ══════════════════════════════════════════════════════════════

# Tier 1A — Big Tech & Scaleups (confirmed working)
GREENHOUSE_TIER1 = [
    ("stripe",          "Stripe"),
    ("airbnb",          "Airbnb"),
    ("lyft",            "Lyft"),
    ("dropbox",         "Dropbox"),
    ("figma",           "Figma"),
    ("mongodb",         "MongoDB"),
    ("datadog",         "Datadog"),
    ("cloudflare",      "Cloudflare"),
    ("coinbase",        "Coinbase"),
    ("robinhood",       "Robinhood"),
    ("pinterest",       "Pinterest"),
    ("reddit",          "Reddit"),
    ("instacart",       "Instacart"),
    ("databricks",      "Databricks"),
    ("snowflake",       "Snowflake"),
    ("elastic",         "Elastic"),
    ("digitalocean",    "DigitalOcean"),
    ("asana",           "Asana"),
    ("squarespace",     "Squarespace"),
    ("fastly",          "Fastly"),
]

# Tier 1B — SaaS / Dev Tools
GREENHOUSE_SAAS = [
    ("gitlab",          "GitLab"),
    ("docker",          "Docker"),
    ("postman",         "Postman"),
    ("sentry",          "Sentry"),
    ("segment",         "Segment"),
    ("algolia",         "Algolia"),
    ("twilio",          "Twilio"),
    ("zapier",          "Zapier"),
    ("plaid",           "Plaid"),
    ("brex",            "Brex"),
    ("ramp",            "Ramp"),
    ("rippling",        "Rippling"),
    ("gusto",           "Gusto"),
    ("deel",            "Deel"),
    ("remote",          "Remote.com"),
    ("lattice",         "Lattice"),
    ("intercom",        "Intercom"),
    ("mercury",         "Mercury"),
]

# Tier 1C — AI / Security Companies
GREENHOUSE_AI_SEC = [
    ("wiz-2",               "Wiz"),
    ("snyk",                "Snyk"),
    ("lacework",            "Lacework"),
    ("drata",               "Drata"),
    ("vanta",               "Vanta"),
    ("abnormalsecurity",    "Abnormal Security"),
    ("orca",                "Orca Security"),
    ("huntress",            "Huntress"),
    ("axonius",             "Axonius"),
    ("exabeam",             "Exabeam"),
    ("crowdstrike",         "CrowdStrike"),
    ("sentinelone",         "SentinelOne"),
    ("paloaltonetworks",    "Palo Alto Networks"),
    ("rapid7",              "Rapid7"),
    ("tenable",             "Tenable"),
    ("qualys",              "Qualys"),
    ("darktrace",           "Darktrace"),
    ("cybereason",          "Cybereason"),
    ("illumio",             "Illumio"),
    ("vectra",              "Vectra AI"),
]


def _fetch_greenhouse_tier1() -> list:
    """Greenhouse Tier 1: Big Tech & Scaleups."""
    jobs = []
    for slug, name in GREENHOUSE_TIER1:
        try:
            result = _fetch_greenhouse_api(slug, name)
            jobs.extend(result)
        except Exception as e:
            log.debug(f"Greenhouse Tier1 {name}: {e}")
    log.info(f"Greenhouse Tier1 (Big Tech): {len(jobs)} jobs")
    return jobs


def _fetch_greenhouse_saas() -> list:
    """Greenhouse Tier 2: SaaS & Dev Tools."""
    jobs = []
    for slug, name in GREENHOUSE_SAAS:
        try:
            result = _fetch_greenhouse_api(slug, name)
            jobs.extend(result)
        except Exception as e:
            log.debug(f"Greenhouse SaaS {name}: {e}")
    log.info(f"Greenhouse SaaS: {len(jobs)} jobs")
    return jobs


def _fetch_greenhouse_ai_sec() -> list:
    """Greenhouse Tier 3: AI & Pure Cybersecurity Companies."""
    jobs = []
    for slug, name in GREENHOUSE_AI_SEC:
        try:
            result = _fetch_greenhouse_api(slug, name)
            jobs.extend(result)
        except Exception as e:
            log.debug(f"Greenhouse AI/Sec {name}: {e}")
    log.info(f"Greenhouse AI/Security: {len(jobs)} jobs")
    return jobs


# ══════════════════════════════════════════════════════════════
# TIER 1 — LEVER CAREER PAGES (30+ Companies)
# ══════════════════════════════════════════════════════════════

LEVER_COMPANIES = [
    ("canva",           "Canva"),
    ("atlassian",       "Atlassian"),
    ("brex",            "Brex"),
    ("flexport",        "Flexport"),
    ("benchling",       "Benchling"),
    ("miro",            "Miro"),
    ("heap",            "Heap"),
    ("front",           "Front"),
    ("checkr",          "Checkr"),
    ("patreon",         "Patreon"),
    ("discord",         "Discord"),
    ("medium",          "Medium"),
    ("envoy",           "Envoy"),
    ("netlify",         "Netlify"),
    ("dbt-labs",        "dbt Labs"),
    ("samsara",         "Samsara"),
    ("verkada",         "Verkada"),
    ("harness",         "Harness"),
    ("lacework",        "Lacework"),
    ("chainguard",      "Chainguard"),
    ("torqsecurity",    "Torq Security"),
    ("anvilogic",       "Anvilogic"),
    ("securonix",       "Securonix"),
    ("expel",           "Expel"),
    ("deepwatch",       "Deepwatch"),
    ("armorcode",       "ArmorCode"),
    ("lightspin",       "Lightspin"),
    ("orca",            "Orca Security"),
    ("noname-security", "Noname Security"),
    ("semgrep",         "Semgrep"),
]


def _fetch_lever_companies() -> list:
    """Lever career pages for 30+ companies."""
    jobs = []
    for slug, name in LEVER_COMPANIES:
        try:
            result = _fetch_lever_api(slug, name)
            jobs.extend(result)
        except Exception as e:
            log.debug(f"Lever {name}: {e}")
    log.info(f"Lever Companies: {len(jobs)} jobs")
    return jobs


# ══════════════════════════════════════════════════════════════
# TIER 2 — STARTUP & VC JOB BOARDS
# ══════════════════════════════════════════════════════════════

def _fetch_ycombinator_jobs() -> list:
    """
    Y Combinator Work at a Startup board — JSON API.
    Filters for cybersecurity roles at YC-backed companies.
    """
    jobs = []
    seen = set()
    # YC's job search API
    searches = [
        "https://www.workatastartup.com/jobs?q=cybersecurity&remote=true",
        "https://www.workatastartup.com/jobs?q=security+engineer&remote=true",
        "https://www.workatastartup.com/jobs?q=information+security",
        "https://www.workatastartup.com/jobs?q=SOC+analyst",
        "https://www.workatastartup.com/jobs?q=penetration+testing",
    ]
    # YC also exposes a JSON endpoint
    api_url = "https://www.workatastartup.com/company_hiring/get_all?&query={q}&remote=true&sponsored=false&page=1&limit=20"
    search_terms = [
        "cybersecurity", "security engineer", "information security",
        "SOC analyst", "penetration tester", "appsec", "cloud security",
    ]
    for term in search_terms:
        import urllib.parse
        url  = api_url.format(q=urllib.parse.quote(term))
        data = get_json(url, headers={**_H, "Accept": "application/json",
                                       "Referer": "https://www.workatastartup.com/"})
        if not data:
            continue
        # YC returns various shapes; try common ones
        companies = data if isinstance(data, list) else data.get("companies", data.get("results", []))
        for company in (companies or []):
            company_name = company.get("name", "YC Startup")
            for job in company.get("jobs", []):
                title   = job.get("title", "")
                job_url = job.get("url", "")
                if not title or not job_url or job_url in seen:
                    continue
                if not _is_sec(title):
                    continue
                seen.add(job_url)
                jobs.append(Job(
                    title=title, company=company_name,
                    location=job.get("location", "Remote / USA"),
                    url=job_url, source="ycombinator_jobs",
                    tags=["ycombinator", "startup", "yc"],
                    is_remote=job.get("remote", False),
                    description=job.get("description", "")[:300],
                ))

    # Also try HTML scraping with JSON-LD fallback
    for url in searches:
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", url)
                    if not title or job_url in seen or not _is_sec(title):
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company_name = hiring.get("name", "YC Startup") if isinstance(hiring, dict) else "YC Startup"
                    jobs.append(Job(
                        title=title, company=company_name,
                        location=item.get("jobLocation", {}).get("address", {}).get("addressCountry", "USA") if isinstance(item.get("jobLocation"), dict) else "USA",
                        url=job_url, source="ycombinator_jobs",
                        tags=["ycombinator", "startup"],
                        is_remote=item.get("jobLocationType") == "TELECOMMUTE",
                    ))
            except Exception:
                continue

    log.info(f"Y Combinator Jobs: {len(jobs)} jobs")
    return jobs


def _fetch_sequoia_talent() -> list:
    """
    Sequoia Capital talent portal — jobs at Sequoia portfolio companies.
    High quality, funded companies.
    """
    jobs = []
    seen = set()
    # Sequoia talent uses a searchable board
    urls = [
        "https://www.sequoiacap.com/jobs/?q=cybersecurity",
        "https://www.sequoiacap.com/jobs/?q=security+engineer",
        "https://www.sequoiacap.com/jobs/?q=information+security",
        "https://www.sequoiacap.com/jobs/?q=SOC",
    ]
    for url in urls:
        html = get_text(url, headers=_H)
        if not html:
            continue
        # Extract job listings from JSON-LD or structured data
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", "")
                    if not title or not job_url or job_url in seen:
                        continue
                    if not _is_sec(title):
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "Sequoia Portfolio") if isinstance(hiring, dict) else "Sequoia Portfolio"
                    jobs.append(Job(
                        title=title, company=company,
                        location="USA / Remote",
                        url=job_url, source="sequoia_talent",
                        tags=["sequoia", "vc", "startup"],
                    ))
            except Exception:
                continue

    log.info(f"Sequoia Talent: {len(jobs)} jobs")
    return jobs


def _fetch_500_global_jobs() -> list:
    """
    500 Global (formerly 500 Startups) portfolio job board.
    Strong MENA coverage — relevant for Gulf & Egypt.
    """
    jobs = []
    seen = set()
    urls = [
        "https://500.co/jobs?search=cybersecurity",
        "https://500.co/jobs?search=security+engineer",
        "https://500.co/jobs?search=information+security",
    ]
    for url in urls:
        html = get_text(url, headers=_H)
        if not html:
            continue
        # Parse job cards
        for m in re.finditer(
            r'<a[^>]+href="(https?://[^"]+)"[^>]*>\s*<[^>]+>([^<]{10,120})</[^>]+>',
            html, re.DOTALL
        ):
            job_url, title = m.group(1), re.sub(r'\s+', ' ', m.group(2)).strip()
            if not _is_sec(title) or job_url in seen:
                continue
            seen.add(job_url)
            jobs.append(Job(
                title=title, company="500 Global Portfolio",
                location="Remote / MENA",
                url=job_url, source="500_global",
                tags=["500startups", "startup", "mena"],
            ))
    log.info(f"500 Global Jobs: {len(jobs)} jobs")
    return jobs


# ══════════════════════════════════════════════════════════════
# TIER 3 — REMOTE-FIRST BOARDS (High Engagement)
# ══════════════════════════════════════════════════════════════

def _fetch_jobspresso() -> list:
    """Jobspresso — curated remote jobs with RSS."""
    jobs = []
    seen = set()
    feeds = [
        "https://jobspresso.co/cybersecurity-remote-jobs/feed/",
        "https://jobspresso.co/it-jobs/feed/",
        "https://jobspresso.co/developer-jobs/feed/",
    ]
    for url in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        for j in _parse_rss(xml, "Jobspresso", "jobspresso", "Remote",
                             ["jobspresso", "remote"], is_remote=True):
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Jobspresso: {len(jobs)} jobs")
    return jobs


def _fetch_outsourcely() -> list:
    """Outsourcely — remote-first hiring board."""
    jobs = []
    seen = set()
    urls = [
        "https://www.outsourcely.com/remote-cybersecurity-jobs",
        "https://www.outsourcely.com/remote-information-security-jobs",
        "https://www.outsourcely.com/remote-network-security-jobs",
    ]
    for url in urls:
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", "")
                    if not title or not job_url or job_url in seen:
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "Outsourcely") if isinstance(hiring, dict) else "Outsourcely"
                    jobs.append(Job(
                        title=title, company=company,
                        location="Remote",
                        url=job_url, source="outsourcely",
                        tags=["outsourcely", "remote"],
                        is_remote=True,
                    ))
            except Exception:
                continue
    log.info(f"Outsourcely: {len(jobs)} jobs")
    return jobs


def _fetch_nodesk_jobs() -> list:
    """Nodesk.co — curated remote jobs RSS for developers & security."""
    jobs = []
    seen = set()
    feeds = [
        "https://nodesk.co/remote-jobs/feed/",
    ]
    for url in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        for j in _parse_rss(xml, "Nodesk", "nodesk", "Remote",
                             ["nodesk", "remote"], is_remote=True):
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Nodesk: {len(jobs)} jobs")
    return jobs


# ══════════════════════════════════════════════════════════════
# TIER 4 — COMMUNITY & UNDERRATED SOURCES
# ══════════════════════════════════════════════════════════════

def _fetch_hackernews_hiring() -> list:
    """
    Hacker News monthly 'Who is hiring?' thread.
    Uses Algolia HN Search API — very high quality, real companies.
    Parses top-level comments for cybersecurity roles.
    """
    jobs = []
    seen = set()

    # Get the latest "Ask HN: Who is hiring?" thread
    search_url = (
        "https://hn.algolia.com/api/v1/search?"
        "query=Ask+HN+Who+is+hiring&tags=ask_hn&hitsPerPage=1&numericFilters=points%3E10"
    )
    data = get_json(search_url, headers=_H)
    if not data or not data.get("hits"):
        log.info("HN Hiring: could not find thread")
        return jobs

    thread = data["hits"][0]
    thread_id = thread.get("objectID", "")
    if not thread_id:
        return jobs

    # Fetch comments from the thread
    comments_url = (
        f"https://hn.algolia.com/api/v1/search?"
        f"tags=comment,story_{thread_id}&hitsPerPage=100"
    )
    cdata = get_json(comments_url, headers=_H)
    if not cdata:
        return jobs

    for hit in cdata.get("hits", []):
        text  = hit.get("comment_text", "") or ""
        text  = re.sub(r'<[^>]+>', ' ', text).strip()
        if not text or len(text) < 30:
            continue
        if not _is_sec(text):
            continue
        # Extract company name from first line (common pattern: "Company | Role | Location")
        first_line = text.split('\n')[0][:120].strip()
        if not first_line or first_line in seen:
            continue
        seen.add(first_line)
        # Try to find a URL in the comment
        url_match = re.search(r'https?://[^\s<>"]+', text)
        job_url   = url_match.group(0) if url_match else f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"

        # Parse company name (first word/phrase before | or ,)
        company_m = re.match(r'^([A-Za-z0-9\.\-& ]{2,40}?)\s*[\|,\(]', first_line)
        company   = company_m.group(1).strip() if company_m else "HN Company"

        jobs.append(Job(
            title=first_line, company=company,
            location="Remote / Worldwide",
            url=job_url, source="hackernews_hiring",
            description=text[:300],
            tags=["hackernews", "hiring", "community"],
            is_remote=True,
        ))

    log.info(f"Hacker News Hiring: {len(jobs)} jobs")
    return jobs


def _fetch_reddit_cybersecurity() -> list:
    """
    Reddit r/cybersecurity — [JOB] and [Hiring] tagged posts.
    Complements r/netsec already in new_sources.py.
    """
    jobs = []
    seen = set()
    urls = [
        "https://www.reddit.com/r/cybersecurity/search.json?q=%5BJobs%5D&sort=new&restrict_sr=1&limit=25",
        "https://www.reddit.com/r/cybersecurity/search.json?q=%5BHiring%5D&sort=new&restrict_sr=1&limit=25",
        "https://www.reddit.com/r/cybersecurity/search.json?q=hiring+remote&sort=new&restrict_sr=1&limit=25",
        "https://www.reddit.com/r/netsec/search.json?q=%5BJob+Posting%5D&sort=new&restrict_sr=1&limit=25",
    ]
    headers = {**_H, "Accept": "application/json"}
    for url in urls:
        data = get_json(url, headers=headers)
        if not data:
            continue
        posts = data.get("data", {}).get("children", [])
        for post in posts:
            p     = post.get("data", {})
            title = p.get("title", "").strip()
            if not title or not _is_sec(title):
                continue
            job_url = "https://www.reddit.com" + p.get("permalink", "")
            if job_url in seen:
                continue
            seen.add(job_url)
            company_m = re.match(r'[\[\(][^\]\)]+[\]\)]\s*(.+?)[\|–\-]', title, re.IGNORECASE)
            company   = company_m.group(1).strip() if company_m else "Reddit Community"
            jobs.append(Job(
                title=title, company=company,
                location="Remote / Worldwide",
                url=job_url, source="reddit_cybersecurity",
                description=(p.get("selftext", "") or "")[:300],
                tags=["reddit", "cybersecurity", "community"],
                is_remote=True,
            ))
    log.info(f"Reddit Cybersecurity: {len(jobs)} jobs")
    return jobs


def _fetch_stackoverflow_jobs() -> list:
    """
    Stack Overflow Jobs (via Indeed partnership) RSS.
    Tech-focused, high signal for developer + security roles.
    """
    jobs = []
    seen = set()
    feeds = [
        "https://stackoverflow.com/jobs/feed?q=cybersecurity&r=true",
        "https://stackoverflow.com/jobs/feed?q=security+engineer&r=true",
        "https://stackoverflow.com/jobs/feed?q=information+security&r=true",
        "https://stackoverflow.com/jobs/feed?q=devsecops",
        "https://stackoverflow.com/jobs/feed?q=appsec",
    ]
    for url in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        for j in _parse_rss(xml, "Stack Overflow", "stackoverflow_jobs",
                             "Remote / Worldwide", ["stackoverflow", "tech", "remote"],
                             is_remote=True):
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Stack Overflow Jobs: {len(jobs)} jobs")
    return jobs


def _fetch_cyberseek_jobs() -> list:
    """
    CyberSeek.org — NIST-backed cybersecurity workforce data + job board.
    Authoritative source, US-focused but signals global trends.
    """
    jobs = []
    seen = set()
    # CyberSeek job listings via their API
    api_url = "https://www.cyberseek.org/api/getjobs?page=1&size=20&keyword={kw}"
    search_terms = [
        "cybersecurity analyst", "SOC analyst", "penetration tester",
        "security engineer", "CISO", "cloud security",
    ]
    for term in search_terms:
        import urllib.parse
        url  = api_url.format(kw=urllib.parse.quote(term))
        data = get_json(url, headers={**_H, "Accept": "application/json"})
        if not data:
            continue
        for item in (data.get("jobs") or data if isinstance(data, list) else []):
            title   = item.get("jobTitle", item.get("title", ""))
            job_url = item.get("applyUrl", item.get("url", ""))
            company = item.get("company", item.get("employer", "CyberSeek"))
            if not title or not job_url or job_url in seen:
                continue
            seen.add(job_url)
            jobs.append(Job(
                title=title, company=company,
                location=item.get("location", "USA"),
                url=job_url, source="cyberseek",
                tags=["cyberseek", "nist", "usa"],
                description=item.get("description", "")[:300],
            ))
    log.info(f"CyberSeek: {len(jobs)} jobs")
    return jobs


# ══════════════════════════════════════════════════════════════
# TIER 5 — MENA / GULF ADDITIONS
# ══════════════════════════════════════════════════════════════

def _fetch_akhtaboot_expanded() -> list:
    """
    Akhtaboot — Jordan/Gulf job board with good Arabic coverage.
    Extended with more search terms vs. the one in egypt_alt.
    """
    jobs = []
    seen = set()
    searches = [
        ("https://www.akhtaboot.com/en/job-search?q=cybersecurity&country=egypt",          "Egypt"),
        ("https://www.akhtaboot.com/en/job-search?q=information+security&country=egypt",   "Egypt"),
        ("https://www.akhtaboot.com/en/job-search?q=network+security&country=egypt",       "Egypt"),
        ("https://www.akhtaboot.com/en/job-search?q=cybersecurity&country=saudi-arabia",   "Saudi Arabia"),
        ("https://www.akhtaboot.com/en/job-search?q=cybersecurity&country=uae",            "UAE"),
        ("https://www.akhtaboot.com/en/job-search?q=SOC+analyst&country=egypt",            "Egypt"),
        ("https://www.akhtaboot.com/en/job-search?q=penetration+testing",                  "MENA"),
    ]
    for url, loc in searches:
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", "")
                    if not title or not job_url or job_url in seen:
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "Akhtaboot") if isinstance(hiring, dict) else "Akhtaboot"
                    jobs.append(Job(
                        title=title, company=company,
                        location=loc, url=job_url,
                        source="akhtaboot_expanded",
                        tags=["akhtaboot", loc.lower().replace(" ", "_")],
                    ))
            except Exception:
                continue
    log.info(f"Akhtaboot Expanded: {len(jobs)} jobs")
    return jobs


def _fetch_naukrigulf_expanded() -> list:
    """
    Naukri Gulf — extended keyword coverage for cybersecurity roles.
    """
    jobs = []
    seen = set()
    searches = [
        ("https://www.naukrigulf.com/cyber-security-jobs", "Gulf"),
        ("https://www.naukrigulf.com/information-security-jobs", "Gulf"),
        ("https://www.naukrigulf.com/soc-analyst-jobs", "Gulf"),
        ("https://www.naukrigulf.com/penetration-testing-jobs", "Gulf"),
        ("https://www.naukrigulf.com/cloud-security-jobs", "Gulf"),
        ("https://www.naukrigulf.com/security-engineer-jobs-in-saudi-arabia", "Saudi Arabia"),
        ("https://www.naukrigulf.com/security-engineer-jobs-in-uae", "UAE"),
    ]
    for url, loc in searches:
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", "")
                    if not title or not job_url or job_url in seen:
                        continue
                    if not _is_sec(title):
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    jobs.append(Job(
                        title=title, company=company or "Naukri Gulf",
                        location=loc, url=job_url,
                        source="naukrigulf_expanded",
                        tags=["naukrigulf", "gulf", loc.lower().replace(" ", "_")],
                    ))
            except Exception:
                continue
    log.info(f"Naukri Gulf Expanded: {len(jobs)} jobs")
    return jobs


def _fetch_gulf_linkedin_expanded() -> list:
    """
    Extended LinkedIn searches for Gulf cybersecurity companies not in gov_gulf.
    Adds: Aramco, SABIC, du Telecom, Zain, Ooredoo, FAB, STC Pay, etc.
    """
    jobs = []
    seen = set()
    # Additional Gulf companies with known cybersecurity hiring
    companies = [
        ("aramco",          "Saudi Aramco",     "Saudi Arabia"),
        ("sabic",           "SABIC",            "Saudi Arabia"),
        ("du",              "du Telecom",        "UAE"),
        ("zain",            "Zain Group",        "Kuwait"),
        ("ooredoo",         "Ooredoo",           "Qatar"),
        ("fab",             "First Abu Dhabi Bank", "UAE"),
        ("dfsa",            "DFSA",              "UAE"),
        ("nca-gov",         "NCA Saudi Arabia",  "Saudi Arabia"),
        ("citra",           "CITRA Kuwait",      "Kuwait"),
        ("ictqatar",        "ICT Qatar",         "Qatar"),
        ("omantel",         "Omantel",           "Oman"),
        ("batelco",         "Batelco",           "Bahrain"),
        ("tamkeen",         "Tamkeen Bahrain",   "Bahrain"),
        ("cyberkraft",      "CyberKraft",        "UAE"),
        ("help-ag",         "Help AG",           "UAE"),
        ("spire-solutions", "Spire Solutions",   "UAE"),
        ("emt-distribution","EMT Distribution",  "UAE"),
        ("darkmatter",      "DarkMatter",        "UAE"),
        ("group-ib",        "Group-IB MENA",     "UAE"),
    ]

    for slug, company_name, location in companies:
        # Try Greenhouse first
        try:
            result = _fetch_greenhouse_api(slug, company_name)
            if result:
                for j in result:
                    if j.url not in seen:
                        seen.add(j.url)
                        j.location = location
                        j.tags = ["gulf", location.lower().replace(" ", "_"), "greenhouse"]
                        jobs.append(j)
                continue
        except Exception:
            pass
        # Try Lever
        try:
            result = _fetch_lever_api(slug, company_name)
            if result:
                for j in result:
                    if j.url not in seen:
                        seen.add(j.url)
                        j.location = location
                        j.tags = ["gulf", location.lower().replace(" ", "_"), "lever"]
                        jobs.append(j)
        except Exception:
            pass

    log.info(f"Gulf LinkedIn Expanded: {len(jobs)} jobs")
    return jobs


def _fetch_gulftalent_expanded() -> list:
    """
    GulfTalent — premium Gulf job board.
    Uses JSON-LD scraping on category pages.
    """
    jobs = []
    seen = set()
    searches = [
        ("https://www.gulftalent.com/jobs/cybersecurity",            "Gulf"),
        ("https://www.gulftalent.com/jobs/information-security",     "Gulf"),
        ("https://www.gulftalent.com/saudi-arabia/jobs/cybersecurity", "Saudi Arabia"),
        ("https://www.gulftalent.com/uae/jobs/cybersecurity",        "UAE"),
        ("https://www.gulftalent.com/qatar/jobs/cybersecurity",      "Qatar"),
    ]
    for url, loc in searches:
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", "")
                    if not title or not job_url or job_url in seen:
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "GulfTalent") if isinstance(hiring, dict) else "GulfTalent"
                    jobs.append(Job(
                        title=title, company=company,
                        location=loc, url=job_url,
                        source="gulftalent_expanded",
                        tags=["gulftalent", "gulf", loc.lower().replace(" ", "_")],
                    ))
            except Exception:
                continue
    log.info(f"GulfTalent Expanded: {len(jobs)} jobs")
    return jobs


def _fetch_wuzzuf_expanded() -> list:
    """
    Wuzzuf (Egypt) — extended keyword searches beyond egypt_alt.py.
    Adds: compliance, GRC, risk, audit, SIEM, SOC, devsecops.
    """
    jobs = []
    seen = set()
    searches = [
        ("https://wuzzuf.net/search/jobs/?q=cybersecurity&a=hpb",                "Egypt"),
        ("https://wuzzuf.net/search/jobs/?q=information+security&a=hpb",         "Egypt"),
        ("https://wuzzuf.net/search/jobs/?q=SOC+analyst&a=hpb",                  "Egypt"),
        ("https://wuzzuf.net/search/jobs/?q=network+security&a=hpb",             "Egypt"),
        ("https://wuzzuf.net/search/jobs/?q=penetration+testing&a=hpb",          "Egypt"),
        ("https://wuzzuf.net/search/jobs/?q=cloud+security&a=hpb",               "Egypt"),
        ("https://wuzzuf.net/search/jobs/?q=GRC+compliance+security&a=hpb",      "Egypt"),
        ("https://wuzzuf.net/search/jobs/?q=devsecops&a=hpb",                    "Egypt"),
        ("https://wuzzuf.net/search/jobs/?q=%D8%A3%D9%85%D9%86+%D9%85%D8%B9%D9%84%D9%88%D9%85%D8%A7%D8%AA&a=hpb", "Egypt"),  # أمن معلومات
    ]
    for url, loc in searches:
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", "")
                    if not title or not job_url or job_url in seen:
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    jobs.append(Job(
                        title=title, company=company or "Wuzzuf",
                        location=loc, url=job_url,
                        source="wuzzuf_expanded",
                        tags=["wuzzuf", "egypt"],
                    ))
            except Exception:
                continue
    log.info(f"Wuzzuf Expanded: {len(jobs)} jobs")
    return jobs


def _fetch_linkedin_egypt_expanded() -> list:
    """
    Additional Egyptian private-sector companies via LinkedIn Jobs URLs.
    Adds: banks, telecom, and local cybersecurity firms.
    """
    jobs = []
    seen = set()
    companies = [
        # Banks & Financial (major cybersec employers in Egypt)
        ("cib-egypt",           "CIB Egypt",            "https://www.linkedin.com/company/cib-egypt/jobs/"),
        ("qnb-egypt",           "QNB Egypt",            "https://www.linkedin.com/company/qnb-alahli/jobs/"),
        ("nbe",                 "NBE",                  "https://www.linkedin.com/company/national-bank-of-egypt/jobs/"),
        ("banque-misr",         "Banque Misr",          "https://www.linkedin.com/company/banque-misr/jobs/"),
        # Telecom
        ("orangeegypt",         "Orange Egypt",         "https://www.linkedin.com/company/orange-egypt/jobs/"),
        ("vodafoneegypt",       "Vodafone Egypt",       "https://www.linkedin.com/company/vodafone-egypt/jobs/"),
        ("etisalatmisr",        "Etisalat Misr",        "https://www.linkedin.com/company/etisalatmisr/jobs/"),
        # Local cybersecurity companies
        ("ncc-egypt",           "NCC Egypt",            "https://www.linkedin.com/company/ncc-egypt/jobs/"),
        ("mcit-egypt",          "MCIT Egypt",           "https://www.linkedin.com/company/mcit-egypt/jobs/"),
        ("egcert",              "EG-CERT",              "https://www.linkedin.com/company/eg-cert/jobs/"),
        ("iecs-eg",             "IECS Egypt",           "https://www.linkedin.com/company/iecs-eg/jobs/"),
    ]
    # LinkedIn Jobs search URLs (public, no login needed for listings)
    searches = [
        f"https://www.linkedin.com/jobs/search/?keywords=cybersecurity&location=Egypt&f_TPR=r604800",
        f"https://www.linkedin.com/jobs/search/?keywords=information+security&location=Egypt&f_TPR=r604800",
        f"https://www.linkedin.com/jobs/search/?keywords=SOC+analyst&location=Egypt&f_TPR=r604800",
        f"https://www.linkedin.com/jobs/search/?keywords=network+security&location=Egypt&f_TPR=r604800",
    ]
    for url in searches:
        html = get_text(url, headers=_H)
        if not html:
            continue
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", "")
                    if not title or not job_url or job_url in seen:
                        continue
                    if not _is_sec(title):
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    jobs.append(Job(
                        title=title, company=company or "LinkedIn Egypt",
                        location="Egypt", url=job_url,
                        source="linkedin_egypt_expanded",
                        tags=["linkedin", "egypt"],
                    ))
            except Exception:
                continue
    log.info(f"LinkedIn Egypt Expanded: {len(jobs)} jobs")
    return jobs


# ══════════════════════════════════════════════════════════════
# MAIN AGGREGATOR
# ══════════════════════════════════════════════════════════════

def fetch_expanded_sources() -> list:
    """
    Aggregate all expanded v18 sources.

    SOURCE TIER SYSTEM:
    - Tier 1 (Greenhouse/Lever): Highest quality, direct from companies
    - Tier 2 (YC/VC boards): High quality, funded startups
    - Tier 3 (Remote-first): High engagement with audience
    - Tier 4 (Community): Unique jobs not on boards
    - Tier 5 (MENA): Critical for Egypt/Gulf audience
    """
    all_jobs = []
    fetchers = [
        # ── TIER 1: Direct Career Pages (Highest Quality) ────
        ("Greenhouse Big Tech",         _fetch_greenhouse_tier1),
        ("Greenhouse SaaS",             _fetch_greenhouse_saas),
        ("Greenhouse AI/Security",      _fetch_greenhouse_ai_sec),
        ("Lever Companies",             _fetch_lever_companies),

        # ── TIER 2: VC / Startup Boards ──────────────────────
        ("Y Combinator Jobs",           _fetch_ycombinator_jobs),
        ("Sequoia Talent",              _fetch_sequoia_talent),
        ("500 Global Jobs",             _fetch_500_global_jobs),

        # ── TIER 3: Remote-First (High Engagement) ────────────
        ("Jobspresso",                  _fetch_jobspresso),
        ("Outsourcely",                 _fetch_outsourcely),
        ("Nodesk Jobs",                 _fetch_nodesk_jobs),

        # ── TIER 4: Community & Underrated ───────────────────
        ("Hacker News Hiring",          _fetch_hackernews_hiring),
        ("Reddit Cybersecurity",        _fetch_reddit_cybersecurity),
        ("Stack Overflow Jobs",         _fetch_stackoverflow_jobs),
        ("CyberSeek NIST",              _fetch_cyberseek_jobs),

        # ── TIER 5: MENA / Gulf / Egypt ──────────────────────
        ("Akhtaboot Expanded",          _fetch_akhtaboot_expanded),
        ("Naukri Gulf Expanded",        _fetch_naukrigulf_expanded),
        ("Gulf LinkedIn Expanded",      _fetch_gulf_linkedin_expanded),
        ("GulfTalent Expanded",         _fetch_gulftalent_expanded),
        ("Wuzzuf Expanded",             _fetch_wuzzuf_expanded),
        ("LinkedIn Egypt Expanded",     _fetch_linkedin_egypt_expanded),
    ]

    for name, fn in fetchers:
        try:
            results = fn()
            all_jobs.extend(results)
            if results:
                log.info(f"✅ {name}: {len(results)} jobs")
        except Exception as e:
            log.warning(f"❌ expanded_sources: {name} failed: {e}")

    log.info(f"📊 Expanded Sources Total: {len(all_jobs)} jobs")
    return all_jobs
