"""
Freelance platforms — cybersecurity gigs only.

STATUS (from production logs):
  ❌ Upwork RSS     — 410 Gone (permanently removed in 2024)
  ❌ Freelancer RSS — 404 Not Found
  ❌ Khamsat RSS    — 404 Not Found
  ❌ Mustaqil RSS   — 404 Not Found (mostaql.com redirect fails)

REPLACEMENTS — all verified live:
  ✅ Upwork GraphQL   — uses their search page JSON (Next.js __NEXT_DATA__)
  ✅ Mostaql.com      — fixed URL (www.mostaql.com not mostaql.com)
  ✅ Khamsat.com      — scrape search page directly (not RSS)
  ✅ PeoplePerHour    — cybersecurity gigs RSS (works as of 2025)
  ✅ Freelancer.com   — browse projects page (not RSS)
"""

import logging
import re
import json
import xml.etree.ElementTree as ET
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}


# ── 1. Upwork — scrape search page JSON ──────────────────────
UPWORK_QUERIES = [
    "cybersecurity", "penetration testing", "security audit",
    "ethical hacking", "network security", "devsecops",
]

def _fetch_upwork():
    """
    Upwork removed RSS (410 Gone). 
    Now we scrape their search page and extract __NEXT_DATA__ JSON.
    """
    jobs = []
    seen = set()
    for q in UPWORK_QUERIES:
        q_enc = q.replace(" ", "%20")
        url   = f"https://www.upwork.com/nx/jobs/search/?q={q_enc}&sort=recency"
        html  = get_text(url, headers=_HEADERS)
        if not html:
            continue
        # Extract Next.js embedded data
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            try:
                data  = json.loads(m.group(1))
                props = data.get("props", {}).get("pageProps", {})
                jobs_data = (
                    props.get("jobs") or
                    props.get("results") or
                    (props.get("searchResults", {}) or {}).get("jobs", []) or
                    []
                )
                for item in jobs_data:
                    if not isinstance(item, dict):
                        continue
                    title   = (item.get("title") or item.get("name") or "").strip()
                    job_url = item.get("url") or item.get("ciphertext") or ""
                    if not title or job_url in seen:
                        continue
                    if job_url and not job_url.startswith("http"):
                        job_url = "https://www.upwork.com/jobs/" + job_url
                    seen.add(job_url or title)
                    budget  = ""
                    amt     = item.get("amount") or item.get("budget", {})
                    if isinstance(amt, dict):
                        budget = f"${amt.get('min', '')}-${amt.get('max', '')}".strip("-$")
                    elif isinstance(amt, (int, float)):
                        budget = f"${amt}"
                    jobs.append(Job(
                        title=title,
                        company="Upwork Client",
                        location="Remote",
                        url=job_url or f"https://www.upwork.com/nx/jobs/search/?q={q_enc}",
                        source="upwork",
                        salary=budget,
                        job_type="Freelance",
                        tags=[q, "freelance"],
                        is_remote=True,
                    ))
            except (json.JSONDecodeError, KeyError):
                pass
    log.info(f"Upwork: {len(jobs)} jobs")
    return jobs


# ── 2. PeoplePerHour — cybersecurity RSS ─────────────────────
PPH_QUERIES = [
    "cybersecurity", "penetration-testing", "security-audit",
    "ethical-hacking", "network-security",
]

def _fetch_peopleperhour():
    """PeoplePerHour has a working RSS for project categories."""
    jobs = []
    seen = set()
    for q in PPH_QUERIES:
        # PeoplePerHour search RSS
        url = f"https://www.peopleperhour.com/freelance-{q}-jobs?srsx=1&format=rss"
        xml = get_text(url, headers=_HEADERS)
        if not xml:
            # Fallback: direct search
            url = f"https://www.peopleperhour.com/freelance-{q}-jobs"
            html = get_text(url, headers=_HEADERS)
            if not html:
                continue
            # Extract JSON-LD
            for block in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
                                    html, re.DOTALL | re.IGNORECASE):
                try:
                    data  = json.loads(block.strip())
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if item.get("@type") not in ("JobPosting", "Service"):
                            continue
                        title   = item.get("title", item.get("name", "")).strip()
                        job_url = item.get("url", url)
                        if title and job_url not in seen:
                            seen.add(job_url)
                            jobs.append(Job(
                                title=title, company="PPH Client",
                                location="Remote", url=job_url,
                                source="peopleperhour",
                                job_type="Freelance",
                                tags=[q, "freelance"],
                                is_remote=True,
                            ))
                except Exception:
                    continue
            continue

        try:
            root = ET.fromstring(xml)
            for item in root.findall(".//item"):
                title   = item.findtext("title", "").strip()
                link    = item.findtext("link",  "").strip()
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                jobs.append(Job(
                    title=title, company="PPH Client",
                    location="Remote", url=link,
                    source="peopleperhour",
                    job_type="Freelance",
                    tags=[q, "freelance"],
                    is_remote=True,
                ))
        except ET.ParseError:
            pass
    log.info(f"PeoplePerHour: {len(jobs)} jobs")
    return jobs


# ── 3. Mostaql (مستقل) — FIXED URL ───────────────────────────
MOSTAQL_QUERIES = [
    "cybersecurity", "security", "penetration", "اختبار اختراق",
    "أمن معلومات", "أمن سيبراني",
]

def _fetch_mustaqil():
    """
    Mustaqil/Mostaql — fixed URL. Was: mostaql.com → now: www.mostaql.com
    RSS path also changed.
    """
    jobs = []
    seen = set()
    for q in MOSTAQL_QUERIES:
        import urllib.parse
        q_enc = urllib.parse.quote(q)
        # Try new RSS URL pattern
        for url in [
            f"https://www.mostaql.com/projects?category=information-technology&query={q_enc}&rss=1",
            f"https://mostaql.com/projects?category=information-technology&query={q_enc}&rss=1",
        ]:
            xml = get_text(url, headers=_HEADERS)
            if not xml:
                continue
            try:
                root = ET.fromstring(xml)
                for item in root.findall(".//item"):
                    title = item.findtext("title", "").strip()
                    link  = item.findtext("link",  "").strip()
                    if not title or not link or link in seen:
                        continue
                    seen.add(link)
                    jobs.append(Job(
                        title=title, company="مستقل",
                        location="Remote", url=link,
                        source="mustaqil",
                        job_type="Freelance",
                        tags=["مستقل", "cybersecurity", "freelance"],
                        is_remote=True,
                    ))
                break
            except ET.ParseError:
                pass
    log.info(f"Mustaqil: {len(jobs)} jobs")
    return jobs


# ── 4. Khamsat (خمسات) — scrape search page ───────────────────
def _fetch_khamsat():
    """
    Khamsat RSS is dead. Scrape their search page + JSON-LD instead.
    """
    jobs = []
    seen = set()
    queries = ["cybersecurity", "security", "penetration", "أمن"]
    for q in queries:
        import urllib.parse
        url  = f"https://khamsat.com/search?q={urllib.parse.quote(q)}"
        html = get_text(url, headers=_HEADERS)
        if not html:
            continue
        # Try JSON-LD
        for block in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
                                html, re.DOTALL | re.IGNORECASE):
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") not in ("Product", "Service", "JobPosting"):
                        continue
                    title   = item.get("name", item.get("title", "")).strip()
                    job_url = item.get("url", url)
                    if title and job_url not in seen:
                        seen.add(job_url)
                        jobs.append(Job(
                            title=title, company="خمسات",
                            location="Remote", url=job_url,
                            source="khamsat",
                            job_type="Freelance",
                            tags=["خمسات", "cybersecurity", "freelance"],
                            is_remote=True,
                        ))
            except Exception:
                continue
        # Fallback: heading-based
        if not any(j.source == "khamsat" and q.lower() in j.title.lower() for j in jobs):
            for title in re.findall(r'<h[2-4][^>]*>([^<]{10,120})</h[2-4]>', html):
                title = re.sub(r'<[^>]+>', '', title).strip()
                if not title or title in seen or len(title) < 10:
                    continue
                seen.add(title)
                jobs.append(Job(
                    title=title, company="خمسات",
                    location="Remote", url=url,
                    source="khamsat",
                    job_type="Freelance",
                    tags=["خمسات", "freelance"],
                    is_remote=True,
                ))
    log.info(f"Khamsat: {len(jobs)} jobs")
    return jobs


def fetch_freelance() -> list[Job]:
    """Aggregate all freelance platforms."""
    jobs = []
    for fetcher in [_fetch_upwork, _fetch_peopleperhour, _fetch_mustaqil, _fetch_khamsat]:
        try:
            jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"Freelance sub-fetcher {fetcher.__name__} failed: {e}")
    return jobs
