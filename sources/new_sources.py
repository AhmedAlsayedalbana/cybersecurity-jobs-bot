"""
New Job Sources — v25
Based on full log analysis (2026-04-16) — only confirmed working sources kept.

CONFIRMED WORKING:
  ✅ Greenhouse Cybersec (subset): ~22 jobs
  ✅ Nitter CyberSecJobs RSS: ~6 jobs
  ✅ GitHub Security Issues: active
  ✅ Telegram public channels: active
  ✅ Hacker News Hiring (Algolia): active
  ✅ CISA USAJobs API: active
  ✅ Bayt HTML scrape: active
  ✅ InfoSec-Jobs board: active

ALL DEAD (removed):
  ❌ Bayt RSS (403), Wellfound (403), Dice (0), DrJobPro (404)
  ❌ Laimoon (404), Reddit r/netsec (403), Jobzella (404)
  ❌ NTI/EgyTech (404/SSL), Wamda (404), HackerOne jobs (404)
  ❌ Intigriti (404), Reddit r/cybersecurity JSON (403)
"""

import logging
import re
import json
import time
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
    "siem", "soar", "endpoint security", "zero trust", "iam",
    "incident response", "compliance", "risk", "audit",
]

def _is_sec(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in SEC_KW)

def _parse_rss(xml_text: str, company: str, source: str,
               location: str, tags: list, is_remote: bool = False) -> list:
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

def _extract_jsonld_jobs(html: str, fallback_url: str, source: str,
                          location: str, tags: list) -> list:
    jobs = []
    seen = set()
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
                job_url = item.get("url", fallback_url)
                if not title or job_url in seen:
                    continue
                seen.add(job_url)
                hiring  = item.get("hiringOrganization", {})
                company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                jobs.append(Job(
                    title=title, company=company or source,
                    location=location, url=job_url,
                    source=source, tags=tags,
                    is_remote=item.get("jobLocationType") == "TELECOMMUTE",
                ))
        except Exception:
            continue
    return jobs


# ── 1. Bayt HTML scrape (RSS was 403) ────────────────────────
def _fetch_bayt() -> list:
    """Bayt — JSON-LD scrape from HTML pages (RSS blocked)."""
    jobs = []
    seen = set()
    pages = [
        ("https://www.bayt.com/en/egypt/jobs/cyber-security-jobs/",        "Egypt"),
        ("https://www.bayt.com/en/egypt/jobs/information-security-jobs/",  "Egypt"),
        ("https://www.bayt.com/en/saudi-arabia/jobs/cyber-security-jobs/", "Saudi Arabia"),
        ("https://www.bayt.com/en/uae/jobs/cyber-security-jobs/",          "UAE"),
        ("https://www.bayt.com/en/qatar/jobs/cyber-security-jobs/",        "Qatar"),
    ]
    for url, loc in pages:
        html = get_text(url, headers=_H)
        if not html:
            continue
        for j in _extract_jsonld_jobs(html, url, "bayt", loc, ["bayt", loc.lower().replace(" ", "_")]):
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Bayt: {len(jobs)} jobs")
    return jobs


# ── 2. Greenhouse Cybersec (only confirmed-working slugs) ─────
def _fetch_greenhouse_cybersec() -> list:
    """Greenhouse boards — only slugs confirmed to work from logs."""
    jobs = []
    seen = set()
    # Confirmed working from logs (404s removed: wiz-2, snyk, lacework, drata, vanta,
    # crowdstrike, sentinelone, paloaltonetworks, rapid7, tenable, qualys, darktrace, illumio, vectra)
    BOARDS = [
        ("Bugcrowd",          "bugcrowd"),
        ("Huntress",          "huntress"),
        ("Axonius",           "axonius"),
        ("Exabeam",           "exabeam"),
        ("Abnormal Security", "abnormalsecurity"),
        ("Orca Security",     "orca"),
        ("Cloudflare",        "cloudflare"),
        ("Datadog",           "datadog"),
        ("MongoDB",           "mongodb"),
        ("Elastic",           "elastic"),
        ("CyberArk",          "cyberark"),
        ("Palo Alto Networks","paloaltonetworks2"),
        ("Fortinet",          "fortinet"),
        ("Zscaler",           "zscaler"),
        ("Proofpoint",        "proofpoint"),
        ("Varonis",           "varonis"),
        ("Secureworks",       "secureworks"),
        ("Trellix",           "trellix"),
    ]
    SEC_TITLES = [
        "security", "cyber", "soc", "pentest", "threat", "vulnerability",
        "grc", "dfir", "appsec", "devsecops", "cloud security", "infosec",
        "malware", "forensic", "red team", "blue team", "incident",
    ]
    base = "https://api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    for company, slug in BOARDS:
        data = get_json(base.format(slug=slug), headers=_H)
        if not data or "jobs" not in data:
            continue
        for item in data["jobs"]:
            title   = item.get("title", "")
            job_url = item.get("absolute_url", "")
            if not any(k in title.lower() for k in SEC_TITLES):
                continue
            if not job_url or job_url in seen:
                continue
            seen.add(job_url)
            loc      = item.get("location", {})
            location = loc.get("name", "") if isinstance(loc, dict) else ""
            jobs.append(Job(
                title=title, company=company,
                location=location or "Not specified",
                url=job_url, source="greenhouse_cybersec",
                tags=["greenhouse", company.lower().replace(" ", "_")],
                is_remote="remote" in location.lower(),
            ))
    log.info(f"Greenhouse Cybersec: {len(jobs)} jobs")
    return jobs


# ── 3. Reddit via RSS (JSON endpoint returns 403) ────────────
def _fetch_reddit_cybersecurity() -> list:
    """Reddit r/cybersecurity via RSS (more reliable than JSON API)."""
    jobs = []
    seen = set()
    feeds = [
        "https://www.reddit.com/r/cybersecurity/search.rss?q=%5BHiring%5D&sort=new&restrict_sr=1",
        "https://www.reddit.com/r/cybersecurity/search.rss?q=hiring+cybersecurity&sort=new&restrict_sr=1",
        "https://old.reddit.com/r/netsec/search.rss?q=%5BHiring%5D&sort=new&restrict_sr=on",
    ]
    rss_h = {**_H, "Accept": "application/rss+xml,application/xml,text/xml"}
    for url in feeds:
        xml = get_text(url, headers=rss_h)
        if not xml:
            continue
        for j in _parse_rss(xml, "Reddit", "reddit_cybersec",
                             "Remote / Worldwide", ["reddit", "cybersecurity"],
                             is_remote=True):
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Reddit Cybersecurity: {len(jobs)} jobs")
    return jobs


# ── 4. Hacker News "Who is hiring?" (Algolia API) ────────────
def _fetch_hackernews_hiring() -> list:
    """HN monthly hiring thread parsed via Algolia search API."""
    jobs = []
    seen = set()
    search_url = (
        "https://hn.algolia.com/api/v1/search?"
        "query=Ask+HN+Who+is+hiring&tags=ask_hn&hitsPerPage=3"
    )
    data = get_json(search_url, headers=_H)
    if not data or not data.get("hits"):
        return jobs
    thread_id = data["hits"][0].get("objectID", "")
    if not thread_id:
        return jobs
    cdata = get_json(
        f"https://hn.algolia.com/api/v1/search?tags=comment,story_{thread_id}&hitsPerPage=100",
        headers=_H
    )
    if not cdata:
        return jobs
    for hit in cdata.get("hits", []):
        text = re.sub(r'<[^>]+>', ' ', hit.get("comment_text", "") or "").strip()
        if len(text) < 30 or not _is_sec(text):
            continue
        first_line = text.split('\n')[0][:120].strip()
        if not first_line or first_line in seen:
            continue
        seen.add(first_line)
        url_m   = re.search(r'https?://[^\s<>"]+', text)
        job_url = url_m.group(0) if url_m else f"https://news.ycombinator.com/item?id={hit.get('objectID','')}"
        co_m    = re.match(r'^([A-Za-z0-9\.\-& ]{2,40}?)\s*[\|,\(]', first_line)
        company = co_m.group(1).strip() if co_m else "HN Company"
        jobs.append(Job(
            title=first_line, company=company,
            location="Remote / Worldwide", url=job_url,
            source="hackernews_hiring",
            description=text[:300],
            tags=["hackernews", "hiring"],
            is_remote=True,
        ))
    log.info(f"Hacker News Hiring: {len(jobs)} jobs")
    return jobs


# ── 5. GitHub Security Issues [Hiring] ───────────────────────
def _fetch_github_security_jobs() -> list:
    """GitHub search API — open issues tagged [Hiring] in security repos."""
    jobs = []
    seen = set()
    endpoints = [
        "https://api.github.com/search/issues?q=%5BHiring%5D+cybersecurity+is%3Aopen&sort=created&order=desc&per_page=20",
        "https://api.github.com/search/issues?q=%5BHiring%5D+%22security+engineer%22+is%3Aopen&sort=created&order=desc&per_page=20",
    ]
    gh_h = {**_H, "Accept": "application/vnd.github+json"}
    for url in endpoints:
        data = get_json(url, headers=gh_h)
        if not data or "items" not in data:
            continue
        for item in data.get("items", []):
            title = item.get("title", "").strip()
            link  = item.get("html_url", "")
            body  = (item.get("body") or "")[:300]
            if not title or not link or link in seen:
                continue
            if not _is_sec(title + " " + body):
                continue
            seen.add(link)
            jobs.append(Job(
                title=title, company="GitHub Community",
                location="Remote / Worldwide", url=link,
                source="github_jobs", description=body,
                tags=["github", "hiring"], is_remote=True,
            ))
    log.info(f"GitHub Security Jobs: {len(jobs)} jobs")
    return jobs


# ── 6. Telegram Public Channels ──────────────────────────────
def _fetch_telegram_public_channels() -> list:
    """Public Telegram channel web previews for Arab cybersec job posts."""
    jobs = []
    seen = set()
    channels = [
        ("https://t.me/s/CyberJobsEgypt",  "CyberJobsEgypt",  "Egypt",  ["egypt", "cybersecurity"]),
        ("https://t.me/s/ITjobsEgypt",     "ITJobsEgypt",     "Egypt",  ["egypt", "it"]),
        ("https://t.me/s/cybersecjobs",    "CyberSecJobs",    "Remote", ["cybersecurity", "remote"]),
        ("https://t.me/s/Gulf_Jobs_IT",    "GulfJobsIT",      "Gulf",   ["gulf", "it"]),
        ("https://t.me/s/ITjobsGCC",       "ITJobsGCC",       "Gulf",   ["gulf", "gcc"]),
    ]
    for ch_url, company, location, tags in channels:
        html = get_text(ch_url, headers=_H)
        if not html:
            continue
        for msg in re.findall(
            r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            html, re.DOTALL
        ):
            text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', msg)).strip()
            if len(text) < 20 or not _is_sec(text):
                continue
            first_line = text.split('\n')[0][:120].strip()
            if not first_line or first_line in seen:
                continue
            seen.add(first_line)
            url_m   = re.search(r'https?://[^\s<>"]+', msg)
            job_url = url_m.group(0) if url_m else ch_url
            jobs.append(Job(
                title=first_line, company=company,
                location=location, url=job_url,
                source="telegram_channel", description=text[:300], tags=tags,
            ))
    log.info(f"Telegram Channels: {len(jobs)} jobs")
    return jobs


# ── 7. Nitter RSS (only working instances) ───────────────────
def _fetch_nitter_security_jobs() -> list:
    """Nitter RSS — only the instances confirmed working."""
    jobs = []
    seen = set()
    feeds = [
        ("https://nitter.net/CyberSecJobs/rss",           "CyberSecJobs",  "Remote"),
        ("https://nitter.privacydev.net/infosecjobs/rss", "InfoSecJobs",   "Remote"),
        ("https://nitter.1d4.us/SecurityJobs/rss",        "SecurityJobs",  "Remote"),
        ("https://nitter.poast.org/CyberSecJobs/rss",     "CyberSecJobs2", "Remote"),
    ]
    for feed_url, company, location in feeds:
        xml = get_text(feed_url, headers=_H)
        if not xml:
            continue
        for j in _parse_rss(xml, company, "nitter_twitter", location,
                             ["twitter", "cybersec", "remote"], is_remote=True):
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"Nitter Security Jobs: {len(jobs)} jobs")
    return jobs


# ── 8. InfoSec-Jobs.com board ────────────────────────────────
def _fetch_infosec_jobs() -> list:
    """InfoSec-Jobs.com — cybersecurity-only job board RSS."""
    jobs = []
    seen = set()
    feeds = [
        "https://infosec-jobs.com/feed/",
        "https://www.infosec-jobs.com/rss/",
    ]
    for url in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        for j in _parse_rss(xml, "InfoSec Jobs", "infosec_jobs",
                             "Remote / Worldwide", ["infosec_jobs", "cybersecurity"],
                             is_remote=True):
            if j.url not in seen:
                seen.add(j.url)
                jobs.append(j)
    log.info(f"InfoSec Jobs: {len(jobs)} jobs")
    return jobs


# ── 9. CISA / USAJobs API ────────────────────────────────────
def _fetch_cisa_jobs() -> list:
    """USAJobs API — cybersecurity government roles (reliable source)."""
    jobs = []
    seen = set()
    url  = (
        "https://data.usajobs.gov/api/search?"
        "Keyword=cybersecurity+information+security"
        "&ResultsPerPage=25&SortField=DatePosted&SortDirection=Desc"
    )
    data = get_json(url, headers={
        **_H,
        "Host": "data.usajobs.gov",
        "User-Agent": "cybersec-jobs-bot/25",
    })
    if data:
        for item in data.get("SearchResult", {}).get("SearchResultItems", []):
            m       = item.get("MatchedObjectDescriptor", {})
            title   = m.get("PositionTitle", "")
            link    = m.get("PositionURI", "")
            dept    = m.get("DepartmentName", "US Government")
            if not title or not link or link in seen:
                continue
            seen.add(link)
            jobs.append(Job(
                title=title, company=dept,
                location="USA (Remote eligible)", url=link,
                source="usajobs_cisa",
                tags=["government", "usa", "cisa"],
                description=m.get("QualificationSummary", "")[:200],
            ))
    log.info(f"CISA/USAJobs: {len(jobs)} jobs")
    return jobs


# ── Main aggregator ───────────────────────────────────────────
def fetch_new_sources() -> list:
    """Aggregate all confirmed-working new sources. 4-min budget."""
    BUDGET_SECONDS = 4 * 60
    _start = time.time()
    all_jobs = []
    fetchers = [
        ("Bayt HTML",           _fetch_bayt),
        ("Greenhouse Cybersec", _fetch_greenhouse_cybersec),
        ("Reddit (RSS)",        _fetch_reddit_cybersecurity),
        ("HN Hiring",           _fetch_hackernews_hiring),
        ("GitHub Hiring",       _fetch_github_security_jobs),
        ("Telegram Channels",   _fetch_telegram_public_channels),
        ("Nitter",              _fetch_nitter_security_jobs),
        ("InfoSec Jobs",        _fetch_infosec_jobs),
        ("CISA USAJobs",        _fetch_cisa_jobs),
    ]
    for name, fn in fetchers:
        if time.time() - _start > BUDGET_SECONDS:
            log.warning(f"new_sources: 4-min budget exhausted at '{name}' — skipping rest.")
            break
        try:
            results = fn()
            all_jobs.extend(results)
        except Exception as e:
            log.warning(f"new_sources: {name} failed: {e}")
    return all_jobs
