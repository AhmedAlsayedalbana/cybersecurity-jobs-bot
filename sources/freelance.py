"""
Freelance Platforms — Arab + Global cybersecurity gigs.

REMOVED (dead — caused all warnings):
  ❌ PeoplePerHour — scrape blocked, 0 results always
  ❌ Guru.com RSS — 404 always

CONFIRMED WORKING:
  ✅ Mostaql (مستقل) — Arab freelance #1, RSS working
  ✅ Khamsat (خمسات) — JSON-LD scrape working
  ✅ Truelancer — RSS feeds working
  ✅ WorkInSecurity.co.uk — UK cybersecurity board RSS
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

def _is_security(text: str) -> bool:
    return any(k in text.lower() for k in SEC_KEYWORDS)


# ── 1. Mostaql (مستقل) ───────────────────────────────────────
def _fetch_mustaqil():
    jobs = []
    seen = set()
    for q in ["cybersecurity", "security", "penetration", "اختبار اختراق", "أمن معلومات"]:
        q_enc = urllib.parse.quote(q)
        url   = f"https://mostaql.com/projects?category=information-technology&query={q_enc}&rss=1"
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
    log.info(f"Mostaql: {len(jobs)} jobs")
    return jobs


# ── 2. Khamsat (خمسات) ───────────────────────────────────────
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
                    if item.get("@type") not in ("Product", "Service", "JobPosting", "Offer"):
                        continue
                    title   = item.get("name", item.get("title", "")).strip()
                    job_url = item.get("url", url)
                    if title and job_url not in seen and _is_security(title):
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


# ── 3. Truelancer RSS ─────────────────────────────────────────
def _fetch_truelancer():
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
    for fetcher in [_fetch_mustaqil, _fetch_khamsat, _fetch_truelancer]:
        try:
            jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"Freelance: {fetcher.__name__} failed: {e}")
    return jobs
"""
Freelance Platforms — Arab + Global cybersecurity gigs.

REMOVED (dead — caused all warnings):
  ❌ PeoplePerHour — scrape blocked, 0 results always
  ❌ Guru.com RSS — 404 always

CONFIRMED WORKING:
  ✅ Mostaql (مستقل) — Arab freelance #1, RSS working
  ✅ Khamsat (خمسات) — JSON-LD scrape working
  ✅ Truelancer — RSS feeds working
  ✅ WorkInSecurity.co.uk — UK cybersecurity board RSS
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

def _is_security(text: str) -> bool:
    return any(k in text.lower() for k in SEC_KEYWORDS)


# ── 1. Mostaql (مستقل) ───────────────────────────────────────
def _fetch_mustaqil():
    jobs = []
    seen = set()
    for q in ["cybersecurity", "security", "penetration", "اختبار اختراق", "أمن معلومات"]:
        q_enc = urllib.parse.quote(q)
        url   = f"https://mostaql.com/projects?category=information-technology&query={q_enc}&rss=1"
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
    log.info(f"Mostaql: {len(jobs)} jobs")
    return jobs


# ── 2. Khamsat (خمسات) ───────────────────────────────────────
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
                    if item.get("@type") not in ("Product", "Service", "JobPosting", "Offer"):
                        continue
                    title   = item.get("name", item.get("title", "")).strip()
                    job_url = item.get("url", url)
                    if title and job_url not in seen and _is_security(title):
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


# ── 3. Truelancer RSS ─────────────────────────────────────────
def _fetch_truelancer():
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


# ── 4. WorkInSecurity.co.uk RSS ──────────────────────────────
def _fetch_workinsecurity():
    jobs = []
    seen = set()
    feeds = [
        "https://workinsecurity.co.uk/feed/",
        "https://workinsecurity.co.uk/jobs/feed/",
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
                desc      = item.findtext("description", "") or ""
                is_remote = "remote" in (title + desc).lower()
                jobs.append(Job(
                    title=title, company="WorkInSecurity",
                    location="Remote" if is_remote else "UK",
                    url=link, source="workinsecurity",
                    tags=["workinsecurity", "uk-security"],
                    is_remote=is_remote,
                ))
            if jobs:
                break
        except ET.ParseError:
            pass
    log.info(f"WorkInSecurity: {len(jobs)} jobs")
    return jobs


def fetch_freelance():
    """Aggregate freelance platforms."""
    jobs = []
    for fetcher in [_fetch_mustaqil, _fetch_khamsat, _fetch_truelancer, _fetch_workinsecurity]:
        try:
            jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"Freelance: {fetcher.__name__} failed: {e}")
    return jobs
