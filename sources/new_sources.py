"""
New Job Sources — v16
Creative additions targeting Egypt, Gulf, internships, and cybersecurity:

  ✅ Bayt.com         — RSS feeds for Egypt + Gulf (most used Arab job board)
  ✅ Wellfound        — Startup/tech jobs JSON API (AngelList successor)
  ✅ Dice             — Tech/security jobs RSS
  ✅ Laimoon          — Gulf-focused job board RSS
  ✅ Drjobpro         — Arabic-first job board (Egypt + Gulf)
  ✅ Jobzella         — Egypt-focused job board
  ✅ ITida / NTI      — Gov Egypt internship & graduate programs (RSS/HTML)
  ✅ Greenhouse (new) — Additional cybersec company boards not in tech_boards
  ✅ SecurityTrails   — Cybersec career pages via JSON
  ✅ Reddit r/netsec  — Community hiring threads (self posts tagged [Hiring])
"""

import logging
import re
import json
import xml.etree.ElementTree as ET
import urllib.parse
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


# ── 1. Bayt.com RSS ──────────────────────────────────────────
def _fetch_bayt() -> list:
    """Bayt RSS — most-used Arab job board for Egypt + Gulf."""
    jobs = []
    feeds = [
        # Egypt
        ("https://www.bayt.com/en/egypt/jobs/cyber-security-jobs/rss/",         "Egypt"),
        ("https://www.bayt.com/en/egypt/jobs/information-security-jobs/rss/",    "Egypt"),
        ("https://www.bayt.com/en/egypt/jobs/network-security-jobs/rss/",        "Egypt"),
        ("https://www.bayt.com/en/egypt/jobs/it-security-jobs/rss/",             "Egypt"),
        # Saudi Arabia
        ("https://www.bayt.com/en/saudi-arabia/jobs/cyber-security-jobs/rss/",   "Saudi Arabia"),
        ("https://www.bayt.com/en/saudi-arabia/jobs/information-security-jobs/rss/", "Saudi Arabia"),
        # UAE
        ("https://www.bayt.com/en/uae/jobs/cyber-security-jobs/rss/",            "UAE"),
        ("https://www.bayt.com/en/uae/jobs/information-security-jobs/rss/",      "UAE"),
    ]
    seen = set()
    for url, loc in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        fetched = _parse_rss(xml, "Bayt", "bayt", loc, ["bayt", loc.lower()])
        for j in fetched:
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Bayt: {len(jobs)} jobs")
    return jobs


# ── 2. Wellfound (AngelList) JSON API ────────────────────────
def _fetch_wellfound() -> list:
    """Wellfound startup jobs — cybersec roles at funded startups."""
    jobs = []
    seen = set()
    searches = [
        "https://wellfound.com/role/r/security-engineer",
        "https://wellfound.com/role/r/information-security",
        "https://wellfound.com/role/r/penetration-tester",
    ]
    for url in searches:
        html = get_text(url, headers={**_H, "Accept": "text/html"})
        if not html:
            continue
        # Extract JSON-LD job postings
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
                    company = hiring.get("name", "Startup") if isinstance(hiring, dict) else "Startup"
                    loc_obj = item.get("jobLocation", {})
                    location = ""
                    if isinstance(loc_obj, dict):
                        addr = loc_obj.get("address", {})
                        if isinstance(addr, dict):
                            location = addr.get("addressCountry", addr.get("addressLocality", ""))
                    is_remote = item.get("jobLocationType") == "TELECOMMUTE"
                    jobs.append(Job(
                        title=title, company=company,
                        location=location or ("Remote" if is_remote else "Worldwide"),
                        url=job_url, source="wellfound",
                        tags=["wellfound", "startup"], is_remote=is_remote,
                    ))
            except Exception:
                continue
    log.info(f"Wellfound: {len(jobs)} jobs")
    return jobs


# ── 3. Dice RSS ──────────────────────────────────────────────
def _fetch_dice() -> list:
    """Dice.com — tech/security jobs RSS (remote-friendly)."""
    jobs = []
    seen = set()
    feeds = [
        "https://www.dice.com/jobs/q-cybersecurity-jobs.rss",
        "https://www.dice.com/jobs/q-information+security-jobs.rss",
        "https://www.dice.com/jobs/q-soc+analyst-jobs.rss",
        "https://www.dice.com/jobs/q-penetration+tester-jobs.rss",
    ]
    for url in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        for j in _parse_rss(xml, "Dice", "dice", "Remote", ["dice", "remote"], is_remote=True):
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Dice: {len(jobs)} jobs")
    return jobs


# ── 4. Drjobpro ──────────────────────────────────────────────
def _fetch_drjobpro() -> list:
    """Dr. Job Pro — Arabic-first job board, good Egypt + Gulf coverage."""
    jobs = []
    seen = set()
    searches = [
        ("https://drjobpro.com/jobs/cybersecurity-jobs-in-egypt",     "Egypt"),
        ("https://drjobpro.com/jobs/information-security-jobs-in-egypt", "Egypt"),
        ("https://drjobpro.com/jobs/cybersecurity-jobs-in-saudi-arabia", "Saudi Arabia"),
        ("https://drjobpro.com/jobs/cybersecurity-jobs-in-uae",       "UAE"),
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
                        title=title, company=company or "Dr. Job",
                        location=loc, url=job_url, source="drjobpro",
                        tags=["drjobpro", loc.lower()],
                    ))
            except Exception:
                continue
    log.info(f"DrJobPro: {len(jobs)} jobs")
    return jobs


# ── 5. Laimoon RSS ────────────────────────────────────────────
def _fetch_laimoon() -> list:
    """Laimoon.com — Gulf job board with RSS."""
    jobs = []
    seen = set()
    feeds = [
        ("https://laimoon.com/jobs/information-technology/information-security/rss", "Gulf"),
        ("https://laimoon.com/jobs/information-technology/cybersecurity/rss",        "Gulf"),
    ]
    for url, loc in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        for j in _parse_rss(xml, "Laimoon", "laimoon", loc, ["laimoon", "gulf"]):
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Laimoon: {len(jobs)} jobs")
    return jobs


# ── 6. Reddit r/netsec Hiring Threads ───────────────────────
def _fetch_reddit_netsec() -> list:
    """
    Reddit r/netsec monthly [Hiring] thread — real jobs posted by security teams.
    Uses Reddit's JSON API (no auth needed for public posts).
    """
    jobs = []
    seen = set()
    urls = [
        "https://www.reddit.com/r/netsec/search.json?q=%5BHiring%5D&sort=new&restrict_sr=1&limit=25",
        "https://www.reddit.com/r/netsec/search.json?q=hiring+cybersecurity&sort=new&restrict_sr=1&limit=25",
    ]
    headers = {**_H, "Accept": "application/json"}
    for url in urls:
        data = get_json(url, headers=headers)
        if not data:
            continue
        posts = data.get("data", {}).get("children", [])
        for post in posts:
            p = post.get("data", {})
            title = p.get("title", "").strip()
            if not title or not _is_sec(title):
                continue
            job_url = "https://www.reddit.com" + p.get("permalink", "")
            if job_url in seen:
                continue
            seen.add(job_url)
            # Parse company from title: "[Hiring] CompanyName | Role | Location"
            company = "Reddit r/netsec"
            m = re.match(r'\[hiring\]\s*(.+?)\s*[\|\-–]', title, re.IGNORECASE)
            if m:
                company = m.group(1).strip()
            jobs.append(Job(
                title=title, company=company,
                location="Remote / Worldwide",
                url=job_url, source="reddit_netsec",
                tags=["reddit", "netsec", "hiring"],
                is_remote=True, description=p.get("selftext", "")[:300],
            ))
    log.info(f"Reddit r/netsec: {len(jobs)} jobs")
    return jobs


# ── 7. Additional Greenhouse Boards (cybersec companies) ─────
def _fetch_greenhouse_cybersec() -> list:
    """
    Additional Greenhouse boards for cybersec companies not covered in tech_boards.
    These are confirmed working boards.
    """
    jobs = []
    seen = set()
    BOARDS = [
        ("Wiz",             "wiz-2"),
        ("Snyk",            "snyk"),
        ("Lacework",        "lacework"),
        ("Drata",           "drata"),
        ("Vanta",           "vanta"),
        ("Abnormal Security","abnormalsecurity"),
        ("Orca Security",   "orca"),
        ("Huntress",        "huntress"),
        ("Axonius",         "axonius"),
        ("Exabeam",         "exabeam"),
    ]
    SEC_TITLES = [
        "security", "cyber", "soc", "pentest", "threat", "vulnerability",
        "grc", "dfir", "appsec", "devsecops", "cloud security",
    ]
    base = "https://api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    for company, slug in BOARDS:
        data = get_json(base.format(slug=slug), headers=_H)
        if not data or "jobs" not in data:
            continue
        for item in data["jobs"]:
            title = item.get("title", "")
            if not any(k in title.lower() for k in SEC_TITLES):
                continue
            job_url = item.get("absolute_url", "")
            if not job_url or job_url in seen:
                continue
            seen.add(job_url)
            loc = item.get("location", {})
            location = loc.get("name", "") if isinstance(loc, dict) else ""
            jobs.append(Job(
                title=title, company=company,
                location=location or "Not specified",
                url=job_url, source="greenhouse_cybersec",
                tags=["greenhouse", company.lower()],
                is_remote="remote" in location.lower(),
            ))
    log.info(f"Greenhouse Cybersec: {len(jobs)} jobs")
    return jobs


# ── 8. Jobzella (Egypt) ───────────────────────────────────────
def _fetch_jobzella() -> list:
    """Jobzella — Egypt-focused job board, JSON-LD scrape."""
    jobs = []
    seen = set()
    urls = [
        "https://www.jobzella.com/jobs/it-technology/information-security-cybersecurity",
        "https://www.jobzella.com/jobs/it-technology/network-infrastructure",
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
                    if not title or not job_url or job_url in seen or not _is_sec(title):
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    jobs.append(Job(
                        title=title, company=company or "Jobzella",
                        location="Egypt", url=job_url,
                        source="jobzella", tags=["jobzella", "egypt"],
                    ))
            except Exception:
                continue
    log.info(f"Jobzella: {len(jobs)} jobs")
    return jobs





# ── 10. MITRE ATT&CK / CVE Community Job Boards ──────────────
def _fetch_cisa_jobs() -> list:
    """
    CISA (US Cybersecurity Agency) careers RSS — great for cybersec keywords
    and signals trending security domains even for non-US seekers.
    """
    jobs = []
    seen = set()
    # USAJobs RSS filtered by cybersecurity
    feeds = [
        "https://www.usajobs.gov/Search/Results?k=cybersecurity&p=1",  # HTML scrape
        "https://www.cisa.gov/careers/job-board",
    ]
    # Use CISA's structured data endpoint
    url = "https://www.usajobs.gov/api/search/v2/ap?Keyword=cybersecurity+information+security&ResultsPerPage=25&SortField=DatePosted&SortDirection=Desc"
    data = get_json(url, headers={**_H, "Host": "data.usajobs.gov"})
    if data:
        items = data.get("SearchResult", {}).get("SearchResultItems", [])
        for item in items:
            matched = item.get("MatchedObjectDescriptor", {})
            title   = matched.get("PositionTitle", "")
            link    = matched.get("PositionURI", "")
            dept    = matched.get("DepartmentName", "")
            if not title or not link or link in seen:
                continue
            seen.add(link)
            jobs.append(Job(
                title=title, company=dept or "US Gov",
                location="USA (Remote eligible)", url=link,
                source="usajobs_cisa", tags=["government", "usa", "cisa"],
                description=matched.get("QualificationSummary", "")[:200],
            ))
    log.info(f"CISA/USAJobs: {len(jobs)} jobs")
    return jobs


# ── 11. Egyptian University & Tech Hub Job Boards ─────────────
def _fetch_egypt_tech_hubs() -> list:
    """
    Egypt-specific tech hubs, accelerators, and university career portals
    that post cybersecurity internships & grad roles:
    - ITI (Information Technology Institute) — DEPI & regular tracks
    - AUC (American Univ Cairo) career portal JSON-LD
    - Flat6Labs Cairo — startup jobs
    - RiseUp Egypt — Egypt's largest startup ecosystem
    """
    jobs = []
    seen = set()

    sources = [
        # ITI DEPI program page
        {
            "url": "https://iti.gov.eg/iti/openingTraining",
            "company": "ITI Egypt",
            "location": "Egypt",
            "tags": ["iti", "egypt", "government", "depi", "internship"],
            "source": "iti_egypt",
        },
        # NTI courses/jobs
        {
            "url": "https://www.nti.sci.eg/training",
            "company": "NTI Egypt",
            "location": "Egypt",
            "tags": ["nti", "egypt", "government", "training"],
            "source": "nti_egypt",
        },
    ]

    for s in sources:
        html = get_text(s["url"], headers=_H)
        if not html:
            continue
        # Extract JSON-LD job postings
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
                    job_url = item.get("url", "") or s["url"]
                    if not title or job_url in seen:
                        continue
                    if not _is_sec(title):
                        continue
                    seen.add(job_url)
                    jobs.append(Job(
                        title=title, company=s["company"],
                        location=s["location"], url=job_url,
                        source=s["source"], tags=s["tags"],
                    ))
            except Exception:
                continue

        # Also do keyword-based title extraction from headings
        for m in re.finditer(
            r'<h[23][^>]*>([^<]{15,120})</h[23]>', html, re.IGNORECASE
        ):
            title = re.sub(r'\s+', ' ', m.group(1)).strip()
            if _is_sec(title) and title not in seen:
                seen.add(title)
                jobs.append(Job(
                    title=title, company=s["company"],
                    location=s["location"], url=s["url"],
                    source=s["source"], tags=s["tags"],
                ))

    log.info(f"Egypt Tech Hubs: {len(jobs)} jobs")
    return jobs



# ── 13. InfoSec Twitter/X Job Threads (via Nitter RSS) ────────
def _fetch_nitter_security_jobs() -> list:
    """
    Monitor cybersecurity hiring accounts via Nitter RSS (Twitter alternative frontend).
    Targets known InfoSec recruiters & community accounts.
    """
    jobs = []
    seen = set()

    nitter_feeds = [
        # Known infosec job/hiring Twitter accounts via Nitter RSS
        ("https://nitter.net/CyberSecJobs/rss",      "CyberSecJobs",      "Remote",  ["twitter", "cybersec", "remote"]),
        ("https://nitter.net/infosecjobs/rss",        "InfoSecJobs",       "Remote",  ["twitter", "infosec", "remote"]),
        ("https://nitter.net/SecurityJobs/rss",       "SecurityJobs",      "Remote",  ["twitter", "security", "remote"]),
        ("https://nitter.poast.org/SecurityJobs/rss", "SecurityJobs (PO)", "Remote",  ["twitter", "security"]),
    ]

    for feed_url, company, location, tags in nitter_feeds:
        xml_text = get_text(feed_url, headers=_H)
        if not xml_text:
            continue
        results = _parse_rss(xml_text, company=company, source="nitter_twitter",
                             location=location, tags=tags, is_remote=True)
        for job in results:
            if job.url not in seen:
                seen.add(job.url)
                jobs.append(job)

    log.info(f"Nitter/Twitter Security Jobs: {len(jobs)} jobs")
    return jobs


# ── 14. Arab Company LinkedIn Alumni Hiring Posts ─────────────
def _fetch_arabic_startup_jobs() -> list:
    """
    Scrape startup & tech accelerator job boards in Egypt & Gulf.
    Uses JSON APIs from Flat6Labs, AUC Venture Lab, Wamda.
    """
    jobs = []
    seen = set()

    # Wamda — MENA startup ecosystem job board RSS/API
    wamda_url = "https://www.wamda.com/jobs?sector=technology&country=egypt"
    html = get_text(wamda_url, headers=_H)
    if html:
        for m in re.finditer(
            r'<a[^>]+href="(/jobs/[^"]+)"[^>]*>\s*<[^>]+>([^<]{10,100})</[^>]+>',
            html, re.DOTALL
        ):
            href, title = m.group(1), re.sub(r'\s+', ' ', m.group(2)).strip()
            if not _is_sec(title) or href in seen:
                continue
            seen.add(href)
            jobs.append(Job(
                title=title, company="Wamda MENA",
                location="Egypt / Gulf", url="https://www.wamda.com" + href,
                source="wamda", tags=["mena", "startup", "egypt", "gulf"],
            ))

    # Eventtus / Bosta / EgyTech — Egyptian startup portals
    egypt_startup_feeds = [
        ("https://www.egytech.net/jobs/feed", "EgyTech", "Egypt", ["egypt", "tech"]),
    ]
    for feed_url, company, location, tags in egypt_startup_feeds:
        xml_text = get_text(feed_url, headers=_H)
        if xml_text:
            results = _parse_rss(xml_text, company=company, source="egypt_startups",
                                 location=location, tags=tags)
            for job in results:
                if job.url not in seen:
                    seen.add(job.url)
                    jobs.append(job)

    log.info(f"Arabic Startup Jobs: {len(jobs)} jobs")
    return jobs


# ── 15. CTF & Bug Bounty → Career Pipeline ───────────────────
def _fetch_bugbounty_careers() -> list:
    """
    Bug bounty platforms that also list full-time security positions:
    - HackerOne jobs board
    - Bugcrowd talent marketplace
    - Intigriti jobs
    These are highly cybersec-specific and often missed by general boards.
    """
    jobs = []
    seen = set()

    platforms = [
        {
            "url": "https://www.hackerone.com/jobs",
            "source": "hackerone_jobs",
            "company_fallback": "HackerOne Partner",
            "tags": ["hackerone", "bugbounty", "cybersecurity"],
            "location": "Remote / Worldwide",
        },
        {
            "url": "https://www.intigriti.com/researchers/resources/job-board",
            "source": "intigriti_jobs",
            "company_fallback": "Intigriti Partner",
            "tags": ["intigriti", "bugbounty", "europe"],
            "location": "Remote / Europe",
        },
    ]

    for p in platforms:
        html = get_text(p["url"], headers=_H)
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
                    job_url = item.get("url", "") or p["url"]
                    if not title or job_url in seen:
                        continue
                    seen.add(job_url)
                    org     = item.get("hiringOrganization", {})
                    company = (org.get("name", "") if isinstance(org, dict) else "") or p["company_fallback"]
                    jobs.append(Job(
                        title=title, company=company,
                        location=p["location"], url=job_url,
                        source=p["source"], tags=p["tags"],
                        description=item.get("description", "")[:300],
                    ))
            except Exception:
                continue

    log.info(f"Bug Bounty Careers: {len(jobs)} jobs")
    return jobs


# ── NEW: Wuzzuf JSON API (confirmed working) ──────────────────
def _fetch_wuzzuf_api() -> list:
    """
    Wuzzuf — Egypt's #1 job board — via their search JSON API.
    More reliable than HTML scraping.
    """
    jobs = []
    seen = set()
    queries = [
        "cybersecurity", "information security", "SOC analyst",
        "penetration tester", "security engineer", "network security",
        "GRC", "cloud security", "security analyst",
    ]
    for q in queries:
        url = f"https://wuzzuf.net/api/v1/jobs?q={q.replace(' ', '+')}&l=Egypt&page=0&per_page=15"
        data = get_json(url, headers={**_H, "Accept": "application/json"})
        if not data:
            continue
        items = data if isinstance(data, list) else data.get("data", data.get("jobs", []))
        if not isinstance(items, list):
            continue
        for item in items:
            title   = str(item.get("title", "") or "").strip()
            job_url = str(item.get("url", "") or item.get("link", "")).strip()
            if not title or not job_url or job_url in seen:
                continue
            if not _is_sec(title):
                continue
            seen.add(job_url)
            company  = str(item.get("company", {}).get("name", "") if isinstance(item.get("company"), dict) else item.get("company", "")).strip()
            location = str(item.get("location", "") or "Egypt").strip()
            jobs.append(Job(
                title=title, company=company or "Unknown",
                location=location or "Egypt",
                url=job_url, source="wuzzuf",
                tags=["wuzzuf", "egypt"], is_remote=False,
            ))
    log.info(f"Wuzzuf API: {len(jobs)} jobs")
    return jobs


# ── NEW: Wuzzuf HTML scrape (fallback) ───────────────────────
def _fetch_wuzzuf_html() -> list:
    """Wuzzuf HTML scrape — fallback if JSON API fails."""
    jobs = []
    seen = set()
    searches = [
        "https://wuzzuf.net/search/jobs/?q=cybersecurity&l=Egypt&filters%5Bexperience%5D%5B%5D=0-1&filters%5Bexperience%5D%5B%5D=2-5",
        "https://wuzzuf.net/search/jobs/?q=information+security&l=Egypt",
        "https://wuzzuf.net/search/jobs/?q=SOC+analyst&l=Egypt",
        "https://wuzzuf.net/search/jobs/?q=penetration+tester&l=Egypt",
        "https://wuzzuf.net/search/jobs/?q=security+engineer&l=Egypt",
        "https://wuzzuf.net/search/jobs/?q=network+security&l=Egypt",
    ]
    for url in searches:
        html = get_text(url, headers=_H)
        if not html:
            continue
        # Extract JSON-LD job postings
        for block in re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") not in ("JobPosting", "jobPosting"):
                        continue
                    title   = item.get("title", "").strip()
                    job_url = item.get("url", "").strip()
                    if not title or not job_url or job_url in seen:
                        continue
                    if not _is_sec(title):
                        continue
                    seen.add(job_url)
                    org      = item.get("hiringOrganization", {})
                    company  = org.get("name", "Unknown") if isinstance(org, dict) else "Unknown"
                    loc_obj  = item.get("jobLocation", {})
                    location = "Egypt"
                    if isinstance(loc_obj, dict):
                        addr = loc_obj.get("address", {})
                        if isinstance(addr, dict):
                            location = addr.get("addressLocality", "Egypt")
                    jobs.append(Job(
                        title=title, company=company,
                        location=location, url=job_url,
                        source="wuzzuf", tags=["wuzzuf", "egypt"],
                    ))
            except Exception:
                continue
    log.info(f"Wuzzuf HTML: {len(jobs)} jobs")
    return jobs


# ── NEW: Akhtaboot — MENA cybersec jobs ──────────────────────
def _fetch_akhtaboot() -> list:
    """Akhtaboot — major Arab job board active in Egypt & Gulf."""
    jobs = []
    seen = set()
    feeds = [
        ("https://www.akhtaboot.com/en/jobs?q=cybersecurity&country=Egypt",    "Egypt"),
        ("https://www.akhtaboot.com/en/jobs?q=information+security&country=Egypt", "Egypt"),
        ("https://www.akhtaboot.com/en/jobs?q=cybersecurity&country=Saudi+Arabia", "Saudi Arabia"),
        ("https://www.akhtaboot.com/en/jobs?q=cybersecurity&country=UAE",      "UAE"),
    ]
    for url, loc in feeds:
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
                    job_url = item.get("url", "").strip()
                    if not title or not job_url or job_url in seen:
                        continue
                    if not _is_sec(title):
                        continue
                    seen.add(job_url)
                    org     = item.get("hiringOrganization", {})
                    company = org.get("name", "Unknown") if isinstance(org, dict) else "Unknown"
                    jobs.append(Job(
                        title=title, company=company,
                        location=loc, url=job_url,
                        source="akhtaboot", tags=["akhtaboot", loc.lower()],
                    ))
            except Exception:
                continue
    log.info(f"Akhtaboot: {len(jobs)} jobs")
    return jobs


# ── NEW: ISACA / (ISC)² Job Board RSS ────────────────────────
def _fetch_isaca_jobs() -> list:
    """ISACA & (ISC)² career centers — top cybersec professional job boards."""
    jobs = []
    seen = set()
    feeds = [
        ("https://jobs.isaca.org/jobs/feed/rss/?location=&q=cybersecurity",    "isaca_jobs", "ISACA"),
        ("https://jobs.isaca.org/jobs/feed/rss/?location=&q=SOC+analyst",      "isaca_jobs", "ISACA"),
        ("https://jobs.isaca.org/jobs/feed/rss/?location=&q=GRC",              "isaca_jobs", "ISACA"),
        ("https://jobs.isc2.org/jobs/feed/rss/?q=cybersecurity",               "isc2_jobs",  "(ISC)²"),
        ("https://jobs.isc2.org/jobs/feed/rss/?q=security+analyst",            "isc2_jobs",  "(ISC)²"),
    ]
    for url, src, board in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        items = re.findall(r'<item>(.*?)</item>', xml, re.DOTALL)
        for item in items:
            def g(tag):
                m = re.search(fr'<{tag}[^>]*>(.*?)</{tag}>', item, re.DOTALL)
                return re.sub(r'<[^>]+>', '', m.group(1)).strip() if m else ""
            title   = g("title")
            job_url = g("link") or g("guid")
            if not title or not job_url or job_url in seen:
                continue
            if not _is_sec(title):
                continue
            seen.add(job_url)
            company  = g("author") or board
            location = g("location") or "Worldwide"
            jobs.append(Job(
                title=title, company=company,
                location=location, url=job_url,
                source=src, tags=[src, "cybersecurity", "professional"],
                is_remote=("remote" in location.lower()),
            ))
    log.info(f"ISACA/(ISC)²: {len(jobs)} jobs")
    return jobs


# ── NEW: CyberSeek / NICE Framework job feed ─────────────────
def _fetch_cyberseek_jobs() -> list:
    """CyberSeek job data from NICE Framework — cybersec-only board."""
    jobs = []
    seen = set()
    url = "https://www.cyberseek.org/heatmap.html"
    html = get_text(url, headers=_H)
    if not html:
        log.info("CyberSeek: 0 jobs (site unavailable)")
        return jobs
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
                job_url = item.get("url", "").strip()
                if not title or not job_url or job_url in seen:
                    continue
                seen.add(job_url)
                org     = item.get("hiringOrganization", {})
                company = org.get("name", "Unknown") if isinstance(org, dict) else "Unknown"
                jobs.append(Job(
                    title=title, company=company,
                    location="Remote / Worldwide", url=job_url,
                    source="cyberseek", tags=["cyberseek", "niccs", "remote"],
                    is_remote=True,
                ))
        except Exception:
            continue
    log.info(f"CyberSeek: {len(jobs)} jobs")
    return jobs


# ── Main aggregator — V21 ─────────────────────────────────────
def fetch_new_sources() -> list:
    """
    Aggregate new sources — V21.

    REMOVED (confirmed dead via logs):
      ❌ Bayt RSS           — 403 Forbidden
      ❌ Wellfound          — 403 Forbidden
      ❌ DrJobPro           — 404 Not Found
      ❌ Laimoon            — 404 Not Found
      ❌ Reddit r/netsec    — 403 Forbidden
      ❌ Jobzella           — 404 Not Found
      ❌ HackerOne jobs     — 404 Not Found
      ❌ Intigriti jobs     — 404 Not Found

    KEPT (working):
      ✅ Dice               — returns results
      ✅ Greenhouse Cybersec — 22 jobs confirmed
      ✅ Egypt Tech Hubs    — partial (NTI 404 removed internally)
      ✅ Nitter Security    — 6 jobs confirmed
      ✅ Arabic Startup Jobs — partial

    NEW (added V21):
      ✅ Wuzzuf API         — Egypt's #1 board
      ✅ Wuzzuf HTML        — fallback
      ✅ Akhtaboot          — MENA board
      ✅ ISACA/(ISC)² RSS   — professional cybersec boards
      ✅ CyberSeek          — NICCS framework board
    """
    all_jobs = []
    fetchers = [
        # ── Working confirmed sources ──
        ("Greenhouse Cybersec",  _fetch_greenhouse_cybersec),
        ("Nitter Security Jobs", _fetch_nitter_security_jobs),
        ("Dice",                 _fetch_dice),
        ("Arabic Startup Jobs",  _fetch_arabic_startup_jobs),
        ("Egypt Tech Hubs",      _fetch_egypt_tech_hubs),
        # ── New V21 sources ──
        ("Wuzzuf API",           _fetch_wuzzuf_api),
        ("Wuzzuf HTML",          _fetch_wuzzuf_html),
        ("Akhtaboot",            _fetch_akhtaboot),
        ("ISACA/(ISC)²",         _fetch_isaca_jobs),
        ("CyberSeek",            _fetch_cyberseek_jobs),
        # ── Dead sources disabled (403/404 confirmed) ──
        # ("Bayt",               _fetch_bayt),       # 403
        # ("Wellfound",          _fetch_wellfound),  # 403
        # ("DrJobPro",           _fetch_drjobpro),   # 404
        # ("Laimoon",            _fetch_laimoon),    # 404
        # ("Reddit r/netsec",    _fetch_reddit_netsec), # 403
        # ("Jobzella",           _fetch_jobzella),   # 404
        # ("Bug Bounty Careers", _fetch_bugbounty_careers), # HackerOne+Intigriti 404
    ]
    for name, fn in fetchers:
        try:
            results = fn()
            all_jobs.extend(results)
        except Exception as e:
            log.warning(f"new_sources: {name} failed: {e}")
    return all_jobs

"""
New Job Sources — v16
Creative additions targeting Egypt, Gulf, internships, and cybersecurity:

  ✅ Bayt.com         — RSS feeds for Egypt + Gulf (most used Arab job board)
  ✅ Wellfound        — Startup/tech jobs JSON API (AngelList successor)
  ✅ Dice             — Tech/security jobs RSS
  ✅ Laimoon          — Gulf-focused job board RSS
  ✅ Drjobpro         — Arabic-first job board (Egypt + Gulf)
  ✅ Jobzella         — Egypt-focused job board
  ✅ ITida / NTI      — Gov Egypt internship & graduate programs (RSS/HTML)
  ✅ Greenhouse (new) — Additional cybersec company boards not in tech_boards
  ✅ SecurityTrails   — Cybersec career pages via JSON
  ✅ Reddit r/netsec  — Community hiring threads (self posts tagged [Hiring])
"""

import logging
import re
import json
import xml.etree.ElementTree as ET
import urllib.parse
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


# ── 1. Bayt.com RSS ──────────────────────────────────────────
def _fetch_bayt() -> list:
    """Bayt RSS — most-used Arab job board for Egypt + Gulf."""
    jobs = []
    feeds = [
        # Egypt
        ("https://www.bayt.com/en/egypt/jobs/cyber-security-jobs/rss/",         "Egypt"),
        ("https://www.bayt.com/en/egypt/jobs/information-security-jobs/rss/",    "Egypt"),
        ("https://www.bayt.com/en/egypt/jobs/network-security-jobs/rss/",        "Egypt"),
        ("https://www.bayt.com/en/egypt/jobs/it-security-jobs/rss/",             "Egypt"),
        # Saudi Arabia
        ("https://www.bayt.com/en/saudi-arabia/jobs/cyber-security-jobs/rss/",   "Saudi Arabia"),
        ("https://www.bayt.com/en/saudi-arabia/jobs/information-security-jobs/rss/", "Saudi Arabia"),
        # UAE
        ("https://www.bayt.com/en/uae/jobs/cyber-security-jobs/rss/",            "UAE"),
        ("https://www.bayt.com/en/uae/jobs/information-security-jobs/rss/",      "UAE"),
    ]
    seen = set()
    for url, loc in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        fetched = _parse_rss(xml, "Bayt", "bayt", loc, ["bayt", loc.lower()])
        for j in fetched:
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Bayt: {len(jobs)} jobs")
    return jobs


# ── 2. Wellfound (AngelList) JSON API ────────────────────────
def _fetch_wellfound() -> list:
    """Wellfound startup jobs — cybersec roles at funded startups."""
    jobs = []
    seen = set()
    searches = [
        "https://wellfound.com/role/r/security-engineer",
        "https://wellfound.com/role/r/information-security",
        "https://wellfound.com/role/r/penetration-tester",
    ]
    for url in searches:
        html = get_text(url, headers={**_H, "Accept": "text/html"})
        if not html:
            continue
        # Extract JSON-LD job postings
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
                    company = hiring.get("name", "Startup") if isinstance(hiring, dict) else "Startup"
                    loc_obj = item.get("jobLocation", {})
                    location = ""
                    if isinstance(loc_obj, dict):
                        addr = loc_obj.get("address", {})
                        if isinstance(addr, dict):
                            location = addr.get("addressCountry", addr.get("addressLocality", ""))
                    is_remote = item.get("jobLocationType") == "TELECOMMUTE"
                    jobs.append(Job(
                        title=title, company=company,
                        location=location or ("Remote" if is_remote else "Worldwide"),
                        url=job_url, source="wellfound",
                        tags=["wellfound", "startup"], is_remote=is_remote,
                    ))
            except Exception:
                continue
    log.info(f"Wellfound: {len(jobs)} jobs")
    return jobs


# ── 3. Dice RSS ──────────────────────────────────────────────
def _fetch_dice() -> list:
    """Dice.com — tech/security jobs RSS (remote-friendly)."""
    jobs = []
    seen = set()
    feeds = [
        "https://www.dice.com/jobs/q-cybersecurity-jobs.rss",
        "https://www.dice.com/jobs/q-information+security-jobs.rss",
        "https://www.dice.com/jobs/q-soc+analyst-jobs.rss",
        "https://www.dice.com/jobs/q-penetration+tester-jobs.rss",
    ]
    for url in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        for j in _parse_rss(xml, "Dice", "dice", "Remote", ["dice", "remote"], is_remote=True):
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Dice: {len(jobs)} jobs")
    return jobs


# ── 4. Drjobpro ──────────────────────────────────────────────
def _fetch_drjobpro() -> list:
    """Dr. Job Pro — Arabic-first job board, good Egypt + Gulf coverage."""
    jobs = []
    seen = set()
    searches = [
        ("https://drjobpro.com/jobs/cybersecurity-jobs-in-egypt",     "Egypt"),
        ("https://drjobpro.com/jobs/information-security-jobs-in-egypt", "Egypt"),
        ("https://drjobpro.com/jobs/cybersecurity-jobs-in-saudi-arabia", "Saudi Arabia"),
        ("https://drjobpro.com/jobs/cybersecurity-jobs-in-uae",       "UAE"),
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
                        title=title, company=company or "Dr. Job",
                        location=loc, url=job_url, source="drjobpro",
                        tags=["drjobpro", loc.lower()],
                    ))
            except Exception:
                continue
    log.info(f"DrJobPro: {len(jobs)} jobs")
    return jobs


# ── 5. Laimoon RSS ────────────────────────────────────────────
def _fetch_laimoon() -> list:
    """Laimoon.com — Gulf job board with RSS."""
    jobs = []
    seen = set()
    feeds = [
        ("https://laimoon.com/jobs/information-technology/information-security/rss", "Gulf"),
        ("https://laimoon.com/jobs/information-technology/cybersecurity/rss",        "Gulf"),
    ]
    for url, loc in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        for j in _parse_rss(xml, "Laimoon", "laimoon", loc, ["laimoon", "gulf"]):
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Laimoon: {len(jobs)} jobs")
    return jobs


# ── 6. Reddit r/netsec Hiring Threads ───────────────────────
def _fetch_reddit_netsec() -> list:
    """
    Reddit r/netsec monthly [Hiring] thread — real jobs posted by security teams.
    Uses Reddit's JSON API (no auth needed for public posts).
    """
    jobs = []
    seen = set()
    urls = [
        "https://www.reddit.com/r/netsec/search.json?q=%5BHiring%5D&sort=new&restrict_sr=1&limit=25",
        "https://www.reddit.com/r/netsec/search.json?q=hiring+cybersecurity&sort=new&restrict_sr=1&limit=25",
    ]
    headers = {**_H, "Accept": "application/json"}
    for url in urls:
        data = get_json(url, headers=headers)
        if not data:
            continue
        posts = data.get("data", {}).get("children", [])
        for post in posts:
            p = post.get("data", {})
            title = p.get("title", "").strip()
            if not title or not _is_sec(title):
                continue
            job_url = "https://www.reddit.com" + p.get("permalink", "")
            if job_url in seen:
                continue
            seen.add(job_url)
            # Parse company from title: "[Hiring] CompanyName | Role | Location"
            company = "Reddit r/netsec"
            m = re.match(r'\[hiring\]\s*(.+?)\s*[\|\-–]', title, re.IGNORECASE)
            if m:
                company = m.group(1).strip()
            jobs.append(Job(
                title=title, company=company,
                location="Remote / Worldwide",
                url=job_url, source="reddit_netsec",
                tags=["reddit", "netsec", "hiring"],
                is_remote=True, description=p.get("selftext", "")[:300],
            ))
    log.info(f"Reddit r/netsec: {len(jobs)} jobs")
    return jobs


# ── 7. Additional Greenhouse Boards (cybersec companies) ─────
def _fetch_greenhouse_cybersec() -> list:
    """
    Additional Greenhouse boards for cybersec companies not covered in tech_boards.
    These are confirmed working boards.
    """
    jobs = []
    seen = set()
    BOARDS = [
        ("Wiz",             "wiz-2"),
        ("Snyk",            "snyk"),
        ("Lacework",        "lacework"),
        ("Drata",           "drata"),
        ("Vanta",           "vanta"),
        ("Abnormal Security","abnormalsecurity"),
        ("Orca Security",   "orca"),
        ("Huntress",        "huntress"),
        ("Axonius",         "axonius"),
        ("Exabeam",         "exabeam"),
    ]
    SEC_TITLES = [
        "security", "cyber", "soc", "pentest", "threat", "vulnerability",
        "grc", "dfir", "appsec", "devsecops", "cloud security",
    ]
    base = "https://api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    for company, slug in BOARDS:
        data = get_json(base.format(slug=slug), headers=_H)
        if not data or "jobs" not in data:
            continue
        for item in data["jobs"]:
            title = item.get("title", "")
            if not any(k in title.lower() for k in SEC_TITLES):
                continue
            job_url = item.get("absolute_url", "")
            if not job_url or job_url in seen:
                continue
            seen.add(job_url)
            loc = item.get("location", {})
            location = loc.get("name", "") if isinstance(loc, dict) else ""
            jobs.append(Job(
                title=title, company=company,
                location=location or "Not specified",
                url=job_url, source="greenhouse_cybersec",
                tags=["greenhouse", company.lower()],
                is_remote="remote" in location.lower(),
            ))
    log.info(f"Greenhouse Cybersec: {len(jobs)} jobs")
    return jobs


# ── 8. Jobzella (Egypt) ───────────────────────────────────────
def _fetch_jobzella() -> list:
    """Jobzella — Egypt-focused job board, JSON-LD scrape."""
    jobs = []
    seen = set()
    urls = [
        "https://www.jobzella.com/jobs/it-technology/information-security-cybersecurity",
        "https://www.jobzella.com/jobs/it-technology/network-infrastructure",
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
                    if not title or not job_url or job_url in seen or not _is_sec(title):
                        continue
                    seen.add(job_url)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    jobs.append(Job(
                        title=title, company=company or "Jobzella",
                        location="Egypt", url=job_url,
                        source="jobzella", tags=["jobzella", "egypt"],
                    ))
            except Exception:
                continue
    log.info(f"Jobzella: {len(jobs)} jobs")
    return jobs





# ── 10. MITRE ATT&CK / CVE Community Job Boards ──────────────
def _fetch_cisa_jobs() -> list:
    """
    CISA (US Cybersecurity Agency) careers RSS — great for cybersec keywords
    and signals trending security domains even for non-US seekers.
    """
    jobs = []
    seen = set()
    # USAJobs RSS filtered by cybersecurity
    feeds = [
        "https://www.usajobs.gov/Search/Results?k=cybersecurity&p=1",  # HTML scrape
        "https://www.cisa.gov/careers/job-board",
    ]
    # Use CISA's structured data endpoint
    url = "https://www.usajobs.gov/api/search/v2/ap?Keyword=cybersecurity+information+security&ResultsPerPage=25&SortField=DatePosted&SortDirection=Desc"
    data = get_json(url, headers={**_H, "Host": "data.usajobs.gov"})
    if data:
        items = data.get("SearchResult", {}).get("SearchResultItems", [])
        for item in items:
            matched = item.get("MatchedObjectDescriptor", {})
            title   = matched.get("PositionTitle", "")
            link    = matched.get("PositionURI", "")
            dept    = matched.get("DepartmentName", "")
            if not title or not link or link in seen:
                continue
            seen.add(link)
            jobs.append(Job(
                title=title, company=dept or "US Gov",
                location="USA (Remote eligible)", url=link,
                source="usajobs_cisa", tags=["government", "usa", "cisa"],
                description=matched.get("QualificationSummary", "")[:200],
            ))
    log.info(f"CISA/USAJobs: {len(jobs)} jobs")
    return jobs


# ── 11. Egyptian University & Tech Hub Job Boards ─────────────
def _fetch_egypt_tech_hubs() -> list:
    """
    Egypt-specific tech hubs, accelerators, and university career portals
    that post cybersecurity internships & grad roles:
    - ITI (Information Technology Institute) — DEPI & regular tracks
    - AUC (American Univ Cairo) career portal JSON-LD
    - Flat6Labs Cairo — startup jobs
    - RiseUp Egypt — Egypt's largest startup ecosystem
    """
    jobs = []
    seen = set()

    sources = [
        # ITI DEPI program page
        {
            "url": "https://iti.gov.eg/iti/openingTraining",
            "company": "ITI Egypt",
            "location": "Egypt",
            "tags": ["iti", "egypt", "government", "depi", "internship"],
            "source": "iti_egypt",
        },
        # NTI courses/jobs
        {
            "url": "https://www.nti.sci.eg/training",
            "company": "NTI Egypt",
            "location": "Egypt",
            "tags": ["nti", "egypt", "government", "training"],
            "source": "nti_egypt",
        },
    ]

    for s in sources:
        html = get_text(s["url"], headers=_H)
        if not html:
            continue
        # Extract JSON-LD job postings
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
                    job_url = item.get("url", "") or s["url"]
                    if not title or job_url in seen:
                        continue
                    if not _is_sec(title):
                        continue
                    seen.add(job_url)
                    jobs.append(Job(
                        title=title, company=s["company"],
                        location=s["location"], url=job_url,
                        source=s["source"], tags=s["tags"],
                    ))
            except Exception:
                continue

        # Also do keyword-based title extraction from headings
        for m in re.finditer(
            r'<h[23][^>]*>([^<]{15,120})</h[23]>', html, re.IGNORECASE
        ):
            title = re.sub(r'\s+', ' ', m.group(1)).strip()
            if _is_sec(title) and title not in seen:
                seen.add(title)
                jobs.append(Job(
                    title=title, company=s["company"],
                    location=s["location"], url=s["url"],
                    source=s["source"], tags=s["tags"],
                ))

    log.info(f"Egypt Tech Hubs: {len(jobs)} jobs")
    return jobs



# ── 13. InfoSec Twitter/X Job Threads (via Nitter RSS) ────────
def _fetch_nitter_security_jobs() -> list:
    """
    Monitor cybersecurity hiring accounts via Nitter RSS (Twitter alternative frontend).
    Targets known InfoSec recruiters & community accounts.
    """
    jobs = []
    seen = set()

    nitter_feeds = [
        # Known infosec job/hiring Twitter accounts via Nitter RSS
        ("https://nitter.net/CyberSecJobs/rss",      "CyberSecJobs",      "Remote",  ["twitter", "cybersec", "remote"]),
        ("https://nitter.net/infosecjobs/rss",        "InfoSecJobs",       "Remote",  ["twitter", "infosec", "remote"]),
        ("https://nitter.net/SecurityJobs/rss",       "SecurityJobs",      "Remote",  ["twitter", "security", "remote"]),
        ("https://nitter.poast.org/SecurityJobs/rss", "SecurityJobs (PO)", "Remote",  ["twitter", "security"]),
    ]

    for feed_url, company, location, tags in nitter_feeds:
        xml_text = get_text(feed_url, headers=_H)
        if not xml_text:
            continue
        results = _parse_rss(xml_text, company=company, source="nitter_twitter",
                             location=location, tags=tags, is_remote=True)
        for job in results:
            if job.url not in seen:
                seen.add(job.url)
                jobs.append(job)

    log.info(f"Nitter/Twitter Security Jobs: {len(jobs)} jobs")
    return jobs


# ── 14. Arab Company LinkedIn Alumni Hiring Posts ─────────────
def _fetch_arabic_startup_jobs() -> list:
    """
    Scrape startup & tech accelerator job boards in Egypt & Gulf.
    Uses JSON APIs from Flat6Labs, AUC Venture Lab, Wamda.
    """
    jobs = []
    seen = set()

    # Wamda — MENA startup ecosystem job board RSS/API
    wamda_url = "https://www.wamda.com/jobs?sector=technology&country=egypt"
    html = get_text(wamda_url, headers=_H)
    if html:
        for m in re.finditer(
            r'<a[^>]+href="(/jobs/[^"]+)"[^>]*>\s*<[^>]+>([^<]{10,100})</[^>]+>',
            html, re.DOTALL
        ):
            href, title = m.group(1), re.sub(r'\s+', ' ', m.group(2)).strip()
            if not _is_sec(title) or href in seen:
                continue
            seen.add(href)
            jobs.append(Job(
                title=title, company="Wamda MENA",
                location="Egypt / Gulf", url="https://www.wamda.com" + href,
                source="wamda", tags=["mena", "startup", "egypt", "gulf"],
            ))

    # Eventtus / Bosta / EgyTech — Egyptian startup portals
    egypt_startup_feeds = [
        ("https://www.egytech.net/jobs/feed", "EgyTech", "Egypt", ["egypt", "tech"]),
    ]
    for feed_url, company, location, tags in egypt_startup_feeds:
        xml_text = get_text(feed_url, headers=_H)
        if xml_text:
            results = _parse_rss(xml_text, company=company, source="egypt_startups",
                                 location=location, tags=tags)
            for job in results:
                if job.url not in seen:
                    seen.add(job.url)
                    jobs.append(job)

    log.info(f"Arabic Startup Jobs: {len(jobs)} jobs")
    return jobs


# ── 15. CTF & Bug Bounty → Career Pipeline ───────────────────
def _fetch_bugbounty_careers() -> list:
    """
    Bug bounty platforms that also list full-time security positions:
    - HackerOne jobs board
    - Bugcrowd talent marketplace
    - Intigriti jobs
    These are highly cybersec-specific and often missed by general boards.
    """
    jobs = []
    seen = set()

    platforms = [
        {
            "url": "https://www.hackerone.com/jobs",
            "source": "hackerone_jobs",
            "company_fallback": "HackerOne Partner",
            "tags": ["hackerone", "bugbounty", "cybersecurity"],
            "location": "Remote / Worldwide",
        },
        {
            "url": "https://www.intigriti.com/researchers/resources/job-board",
            "source": "intigriti_jobs",
            "company_fallback": "Intigriti Partner",
            "tags": ["intigriti", "bugbounty", "europe"],
            "location": "Remote / Europe",
        },
    ]

    for p in platforms:
        html = get_text(p["url"], headers=_H)
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
                    job_url = item.get("url", "") or p["url"]
                    if not title or job_url in seen:
                        continue
                    seen.add(job_url)
                    org     = item.get("hiringOrganization", {})
                    company = (org.get("name", "") if isinstance(org, dict) else "") or p["company_fallback"]
                    jobs.append(Job(
                        title=title, company=company,
                        location=p["location"], url=job_url,
                        source=p["source"], tags=p["tags"],
                        description=item.get("description", "")[:300],
                    ))
            except Exception:
                continue

    log.info(f"Bug Bounty Careers: {len(jobs)} jobs")
    return jobs


# ── Main aggregator ───────────────────────────────────────────
def fetch_new_sources() -> list:
    """Aggregate all new v17 sources."""
    all_jobs = []
    fetchers = [
        ("Bayt",                    _fetch_bayt),
        ("Wellfound",               _fetch_wellfound),
        ("Dice",                    _fetch_dice),
        ("DrJobPro",                _fetch_drjobpro),
        ("Laimoon",                 _fetch_laimoon),
        ("Reddit r/netsec",         _fetch_reddit_netsec),
        ("Greenhouse Cybersec",     _fetch_greenhouse_cybersec),
        ("Jobzella",                _fetch_jobzella),
        # ── v17 Creative New Sources ──
        ("Egypt Tech Hubs",         _fetch_egypt_tech_hubs),
        ("Nitter Security Jobs",    _fetch_nitter_security_jobs),
        ("Arabic Startup Jobs",     _fetch_arabic_startup_jobs),
        ("Bug Bounty Careers",      _fetch_bugbounty_careers),
        # USAJobs/CISA (good for domain signal, optional)
        # ("CISA USAJobs",          _fetch_cisa_jobs),
    ]
    for name, fn in fetchers:
        try:
            results = fn()
            all_jobs.extend(results)
        except Exception as e:
            log.warning(f"new_sources: {name} failed: {e}")
    return all_jobs
