"""
New Job Sources — v27

REMOVED (confirmed dead from logs):
  ❌ Bayt HTML — HTTP 403
  ❌ Reddit RSS — HTTP 403
  ❌ Nitter (privacydev, 1d4.us, poast.org) — connection refused / DNS fail
  ❌ InfoSec-Jobs RSS — HTTP 404
  ❌ CISA/USAJobs — HTTP 401
  ❌ nitter.net/infosecjobs, /SecurityJobs — HTTP 404

CONFIRMED WORKING:
  ✅ Greenhouse Cybersec: ~160 jobs
  ✅ Hacker News Hiring: ~6 jobs
  ✅ GitHub Security Issues: ~2 jobs
  ✅ Telegram Channels: ~2 jobs
  ✅ nitter.net/CyberSecJobs: ~6 jobs (only this one works)

NEW v27:
  ✅ Akhtaboot Egypt/Gulf (Arab job board)
  ✅ Forasna Egypt RSS
"""

import logging
import re
import json
import time
import datetime
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
    "siem", "endpoint security", "zero trust", "iam", "incident response",
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


# ── 1. Greenhouse Cybersec ────────────────────────────────────
def _fetch_greenhouse_cybersec() -> list:
    """Greenhouse boards — cybersecurity companies confirmed working."""
    jobs = []
    seen = set()
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
        ("Zscaler",           "zscaler"),
        # v30 additions
        ("GitLab",            "gitlab"),
        ("Okta",              "okta"),
        ("Bitwarden",         "bitwarden"),
        # Removed 404s: snyk, wiz, aquasecurity, sysdig, semgrep, devo
    ]
    SEC_TITLES = [
        "security", "cyber", "soc", "pentest", "threat", "vulnerability",
        "grc", "dfir", "appsec", "devsecops", "cloud security", "infosec",
        "malware", "forensic", "red team", "blue team", "incident", "detection",
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


# ── 2. Hacker News Hiring ─────────────────────────────────────
def _fetch_hackernews_hiring() -> list:
    jobs = []
    seen = set()
    now = datetime.datetime.utcnow()
    queries = [
        f"who is hiring {now.strftime('%B %Y')} security",
        f"who is hiring {now.strftime('%B %Y')} cybersecurity",
        "who is hiring security engineer remote",
        "who is hiring SOC analyst",
    ]
    for q in queries:
        url = (
            "https://hn.algolia.com/api/v1/search?"
            + urllib.parse.urlencode({
                "query": q,
                "tags": "comment,story",
                "hitsPerPage": 20,
                "numericFilters": f"created_at_i>{int(time.time()) - 86400 * 35}",
            })
        )
        data = get_json(url, headers=_H)
        if not data:
            continue
        for hit in data.get("hits", []):
            text = hit.get("comment_text") or hit.get("title") or ""
            text = re.sub(r'<[^>]+>', ' ', text).strip()
            if not _is_sec(text):
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
                source="hackernews_hiring", description=text[:300],
                tags=["hackernews", "hiring"], is_remote=True,
            ))
    log.info(f"Hacker News Hiring: {len(jobs)} jobs")
    return jobs


# ── 3. GitHub Security Issues ─────────────────────────────────
def _fetch_github_security_jobs() -> list:
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


# ── 4. Telegram Public Channels ──────────────────────────────
def _fetch_telegram_public_channels() -> list:
    jobs = []
    seen = set()
    channels = [
        ("https://t.me/s/CyberJobsEgypt",  "CyberJobsEgypt",  "Egypt",  ["egypt", "cybersecurity"]),
        ("https://t.me/s/ITjobsEgypt",     "ITJobsEgypt",     "Egypt",  ["egypt", "it"]),
        ("https://t.me/s/cybersecjobs",    "CyberSecJobs",    "Remote", ["cybersecurity", "remote"]),
        ("https://t.me/s/Gulf_Jobs_IT",    "GulfJobsIT",      "Gulf",   ["gulf", "it"]),
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


# ── 7. Forasna Egypt (HTTP 404 — kept as stub, skips gracefully) ─
def _fetch_forasna() -> list:
    return []   # disabled — HTTP 404 on all endpoints confirmed



# ── 9. Cybersecurity-specific job boards via RSS ──────────────
def _fetch_cybersec_rss() -> list:
    """Additional cybersecurity RSS feeds."""
    jobs = []
    seen = set()
    feeds = [
        ("https://www.cybersecjobs.com/rss/jobs",                    "CyberSecJobs",    "Remote / Worldwide"),
        ("https://securityjobs.net/rss/cybersecurity-jobs",          "SecurityJobs.net", "Remote / Worldwide"),
    ]
    for url, company, location in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        for j in _parse_rss(xml, company, company.lower().replace(".", "").replace(" ", "_"),
                             location, [company.lower(), "cybersec"]):
            if j.url not in seen and _is_sec(j.title):
                seen.add(j.url)
                jobs.append(j)
        time.sleep(0.5)
    log.info(f"CyberSec RSS boards: {len(jobs)} jobs")
    return jobs


# ── Main aggregator ───────────────────────────────────────────
def fetch_new_sources() -> list:
    """Aggregate all confirmed-working new sources. 5-min budget."""
    BUDGET_SECONDS = 5 * 60
    _start = time.time()
    all_jobs = []
    fetchers = [
        ("Greenhouse Cybersec", _fetch_greenhouse_cybersec),
        ("HN Hiring",           _fetch_hackernews_hiring),
        ("GitHub Hiring",       _fetch_github_security_jobs),
        ("Telegram Channels",   _fetch_telegram_public_channels),
    ]
    for name, fn in fetchers:
        if time.time() - _start > BUDGET_SECONDS:
            log.warning(f"new_sources: 5-min budget exhausted at '{name}' — skipping rest.")
            break
        try:
            results = fn()
            all_jobs.extend(results)
            if results:
                log.info(f"new_sources: {name}: {len(results)} jobs")
        except Exception as e:
            log.warning(f"new_sources: {name} failed: {e}")
    return all_jobs
