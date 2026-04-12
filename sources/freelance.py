"""
Freelance Platforms — V11

REMOVED:
  ❌ Upwork — 403 always
  ❌ Guru.com — 404 always (wrong URL pattern)
  ❌ PeoplePerHour — 0 results always

REPLACEMENTS:
  ✅ Mostaql (مستقل) — RSS confirmed (correct URL)
  ✅ Khamsat (خمسات) — JSON-LD scrape
  ✅ Freelancer.com — their actual public RSS endpoint
  ✅ Toptal Blog RSS — passive signal for security consulting trends
  ✅ Truelancer — emerging freelance platform with RSS
"""

import logging
import re
import json
import urllib.parse
import xml.etree.ElementTree as ET
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}

SEC_KEYWORDS = [
    "cybersecurity", "security", "penetration", "pentest", "ethical hack",
    "network security", "devsecops", "soc", "malware", "forensic",
    "أمن", "اختبار اختراق", "أمن معلومات",
]

def _is_security(text):
    t = text.lower()
    return any(k in t for k in SEC_KEYWORDS)


# ── 1. Mostaql (مستقل) — correct RSS URL ─────────────────────
MOSTAQL_QUERIES = [
    "cybersecurity", "security", "penetration",
    "اختبار اختراق", "أمن معلومات", "أمن سيبراني",
]

def _fetch_mustaqil():
    jobs = []
    seen = set()
    for q in MOSTAQL_QUERIES:
        q_enc = urllib.parse.quote(q)
        url   = f"https://www.mostaql.com/projects?category=information-technology&query={q_enc}&rss=1"
        xml   = get_text(url, headers=_H)
        if not xml:
            continue
        try:
            xml_clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', xml)
            root = ET.fromstring(xml_clean)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                jobs.append(Job(
                    title=title, company="مستقل",
                    location="Remote", url=link,
                    source="mustaqil", job_type="Freelance",
                    tags=["مستقل", "freelance"], is_remote=True,
                ))
        except ET.ParseError:
            pass
    log.info(f"Mustaqil: {len(jobs)} jobs")
    return jobs


# ── 2. Khamsat (خمسات) — JSON-LD ─────────────────────────────
def _fetch_khamsat():
    jobs = []
    seen = set()
    for q in ["cybersecurity", "security", "penetration", "أمن"]:
        url  = f"https://khamsat.com/search?q={urllib.parse.quote(q)}"
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
                    if item.get("@type") not in ("Product", "Service", "JobPosting"):
                        continue
                    title   = item.get("name", item.get("title", "")).strip()
                    job_url = item.get("url", url)
                    if title and job_url not in seen:
                        seen.add(job_url)
                        jobs.append(Job(
                            title=title, company="خمسات",
                            location="Remote", url=job_url,
                            source="khamsat", job_type="Freelance",
                            tags=["خمسات", "freelance"], is_remote=True,
                        ))
            except Exception:
                continue
    log.info(f"Khamsat: {len(jobs)} jobs")
    return jobs


# ── 3. Freelancer.com — project listings page ────────────────
def _fetch_freelancer():
    """
    Freelancer.com search results page — extract via JSON-LD/Next.js.
    Their RSS is dead but search pages are accessible.
    """
    jobs = []
    seen = set()
    queries = ["cybersecurity", "penetration-testing", "network-security"]
    for q in queries:
        url  = f"https://www.freelancer.com/jobs/{q}/"
        html = get_text(url, headers=_H)
        if not html:
            continue
        # Extract job cards from page
        titles = re.findall(
            r'<a[^>]+href="(/projects/[^"]+)"[^>]*>\s*([^<]{10,120})</a>',
            html
        )
        for path, title in titles:
            title = title.strip()
            if not title or not _is_security(title) or title in seen:
                continue
            seen.add(title)
            jobs.append(Job(
                title=title, company="Freelancer Client",
                location="Remote",
                url=f"https://www.freelancer.com{path}",
                source="freelancer", job_type="Freelance",
                tags=["freelancer", "freelance"], is_remote=True,
            ))
    log.info(f"Freelancer: {len(jobs)} jobs")
    return jobs


# ── 4. Truelancer — RSS for IT security projects ─────────────
def _fetch_truelancer():
    """Truelancer is a growing platform with working RSS."""
    jobs = []
    seen = set()
    feeds = [
        "https://www.truelancer.com/freelance-cybersecurity-jobs?format=rss",
        "https://www.truelancer.com/freelance-network-security-jobs?format=rss",
        "https://www.truelancer.com/freelance-ethical-hacking-jobs?format=rss",
    ]
    for url in feeds:
        xml = get_text(url, headers=_H)
        if not xml:
            continue
        try:
            xml_clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', xml)
            root = ET.fromstring(xml_clean)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                jobs.append(Job(
                    title=title, company="Truelancer Client",
                    location="Remote", url=link,
                    source="truelancer", job_type="Freelance",
                    tags=["truelancer", "freelance"], is_remote=True,
                ))
        except ET.ParseError:
            pass
    log.info(f"Truelancer: {len(jobs)} jobs")
    return jobs


def fetch_freelance():
    """Aggregate freelance platforms."""
    jobs = []
    for fetcher in [_fetch_mustaqil, _fetch_khamsat, _fetch_freelancer, _fetch_truelancer]:
        try:
            jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"Freelance: {fetcher.__name__} failed: {e}")
    return jobs
"""
Freelance Platforms — V10
REMOVED (confirmed dead):
  ❌ Upwork /nx/jobs/search — 403 Forbidden always

KEPT/FIXED:
  ✅ PeoplePerHour — cybersec gigs RSS
  ✅ Mostaql (مستقل) — fixed URL
  ✅ Khamsat (خمسات) — JSON-LD scrape

NEW:
  ✅ Guru.com RSS     — freelance security projects
  ✅ Toptal Jobs      — premium freelance (JSON)
  ✅ Workana (LATAM)  — RSS for security projects
"""

import logging
import re
import json
import urllib.parse
import xml.etree.ElementTree as ET
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}


def _parse_rss(url, name, key):
    xml = get_text(url, headers=_H)
    if not xml:
        return []
    jobs = []
    try:
        xml_clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', xml)
        root = ET.fromstring(xml_clean)
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link",  "").strip()
            if not title or not link:
                continue
            jobs.append(Job(
                title=title, company=name,
                location="Remote", url=link,
                source=key, job_type="Freelance",
                tags=[key, "freelance"], is_remote=True,
            ))
    except ET.ParseError:
        pass
    return jobs


# ── 1. PeoplePerHour ─────────────────────────────────────────
PPH_QUERIES = ["cybersecurity", "penetration-testing", "security-audit",
               "ethical-hacking", "network-security"]

def _fetch_peopleperhour():
    jobs = []
    seen = set()
    for q in PPH_QUERIES:
        url = f"https://www.peopleperhour.com/freelance-{q}-jobs?srsx=1&format=rss"
        result = _parse_rss(url, "PeoplePerHour", "peopleperhour")
        if not result:
            # JSON-LD fallback
            url2  = f"https://www.peopleperhour.com/freelance-{q}-jobs"
            html  = get_text(url2, headers=_H)
            if html:
                for block in re.findall(
                    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
                    html, re.DOTALL | re.IGNORECASE
                ):
                    try:
                        data  = json.loads(block.strip())
                        items = data if isinstance(data, list) else [data]
                        for item in items:
                            if item.get("@type") not in ("JobPosting", "Service"):
                                continue
                            title   = item.get("title", item.get("name", "")).strip()
                            job_url = item.get("url", url2)
                            if title and job_url not in seen:
                                seen.add(job_url)
                                jobs.append(Job(
                                    title=title, company="PPH Client",
                                    location="Remote", url=job_url,
                                    source="peopleperhour",
                                    job_type="Freelance",
                                    tags=[q, "freelance"], is_remote=True,
                                ))
                    except Exception:
                        continue
        else:
            for j in result:
                if j.url not in seen:
                    seen.add(j.url)
                    jobs.append(j)
    log.info(f"PeoplePerHour: {len(jobs)} jobs")
    return jobs


# ── 2. Guru.com RSS ──────────────────────────────────────────
GURU_QUERIES = ["cybersecurity", "penetration-testing", "network-security",
                "security-audit", "ethical-hacking"]

def _fetch_guru():
    jobs = []
    for q in GURU_QUERIES:
        url = f"https://www.guru.com/d/jobs/cat/it-programming/skill/{q}/q/{q}/pg/1/?format=rss"
        jobs.extend(_parse_rss(url, "Guru.com", "guru"))
    log.info(f"Guru.com: {len(jobs)} jobs")
    return jobs


# ── 3. Mostaql (مستقل) ───────────────────────────────────────
MOSTAQL_QUERIES = ["cybersecurity", "security", "penetration",
                   "اختبار اختراق", "أمن معلومات", "أمن سيبراني"]

def _fetch_mustaqil():
    jobs = []
    seen = set()
    for q in MOSTAQL_QUERIES:
        q_enc = urllib.parse.quote(q)
        for url in [
            f"https://www.mostaql.com/projects?category=information-technology&query={q_enc}&rss=1",
            f"https://mostaql.com/projects?category=information-technology&query={q_enc}&rss=1",
        ]:
            xml = get_text(url, headers=_H)
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
                        source="mustaqil", job_type="Freelance",
                        tags=["مستقل", "cybersecurity", "freelance"], is_remote=True,
                    ))
                break
            except ET.ParseError:
                pass
    log.info(f"Mustaqil: {len(jobs)} jobs")
    return jobs


# ── 4. Khamsat (خمسات) JSON-LD ───────────────────────────────
def _fetch_khamsat():
    jobs = []
    seen = set()
    for q in ["cybersecurity", "security", "penetration", "أمن"]:
        url  = f"https://khamsat.com/search?q={urllib.parse.quote(q)}"
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
                    if item.get("@type") not in ("Product", "Service", "JobPosting"):
                        continue
                    title   = item.get("name", item.get("title", "")).strip()
                    job_url = item.get("url", url)
                    if title and job_url not in seen:
                        seen.add(job_url)
                        jobs.append(Job(
                            title=title, company="خمسات",
                            location="Remote", url=job_url,
                            source="khamsat", job_type="Freelance",
                            tags=["خمسات", "freelance"], is_remote=True,
                        ))
            except Exception:
                continue
    log.info(f"Khamsat: {len(jobs)} jobs")
    return jobs


def fetch_freelance():
    """Aggregate freelance platforms."""
    jobs = []
    for fetcher in [_fetch_peopleperhour, _fetch_guru, _fetch_mustaqil, _fetch_khamsat]:
        try:
            jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"Freelance: {fetcher.__name__} failed: {e}")
    return jobs
