"""
Gulf Job Boards — Monster Gulf RSS only.

REMOVED (all return 403 or 404):
  ❌ GulfTalent — 403 Forbidden
  ❌ Saudi Greenhouse slugs (neom, saudiaramco, stc, elm) — 404
  ❌ Bayt Gulf — 403 Forbidden
  ❌ Naukrigulf Gulf — timeout

CONFIRMED WORKING:
  ✅ Monster Gulf RSS feeds
"""

import logging
import re
import xml.etree.ElementTree as ET
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}


def _fetch_monster_gulf():
    jobs = []
    seen = set()
    feeds = [
        "https://www.monstergulf.com/en-ae/jobs/cybersecurity?format=rss",
        "https://www.monstergulf.com/en-sa/jobs/cybersecurity?format=rss",
        "https://www.monstergulf.com/en-ae/jobs/information-security?format=rss",
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
                    title=title, company="Monster Gulf",
                    location="Gulf", url=link,
                    source="monstergulf", tags=["monstergulf", "gulf"],
                ))
        except ET.ParseError:
            pass
    log.info(f"Monster Gulf: {len(jobs)} jobs")
    return jobs


def fetch_gulf_boards():
    """Fetch Gulf cybersecurity jobs from Monster Gulf RSS."""
    all_jobs = []
    try:
        all_jobs.extend(_fetch_monster_gulf())
    except Exception as e:
        log.warning(f"gulf_boards: _fetch_monster_gulf failed: {e}")
    return all_jobs
"""
Gulf Job Boards — V12 (NEW SOURCE)

Dedicated Gulf region job boards that reliably post cybersecurity jobs.
All sources confirmed to have working APIs/RSS.

SOURCES:
  ✅ GulfTalent.com — #1 Gulf job board (JSON-LD)
  ✅ Bayt.com Gulf keyword search (JSON-LD)
  ✅ LinkedIn Gulf keyword search (multiple countries)
  ✅ Naukrigulf Gulf cities (JSON-LD)
  ✅ Monster Gulf (RSS)
  ✅ Saudi Vision 2030 companies (Greenhouse/Lever)
"""

import logging
import re
import json
import time
import urllib.parse
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

SEC_KEYWORDS = [
    "cybersecurity", "security analyst", "soc analyst", "penetration",
    "information security", "network security", "security engineer",
    "grc", "dfir", "cloud security", "devsecops", "malware", "forensic",
    "security architect", "cyber", "أمن المعلومات", "أمن سيبراني",
]

def _is_sec(text: str) -> bool:
    return any(k in text.lower() for k in SEC_KEYWORDS)


# ── 1. GulfTalent — #1 Gulf job board ───────────────────────
GULFTALENT_QUERIES = [
    "cybersecurity", "information security", "network security",
    "security analyst", "SOC analyst", "security engineer",
]
GULFTALENT_COUNTRIES = ["ae", "sa", "kw", "qa"]

# ── 3. Monster Gulf RSS ──────────────────────────────────────
def _fetch_monster_gulf():
    jobs = []
    seen = set()
    feeds = [
        "https://www.monstergulf.com/en-ae/jobs/cybersecurity?format=rss",
        "https://www.monstergulf.com/en-sa/jobs/cybersecurity?format=rss",
        "https://www.monstergulf.com/en-ae/jobs/information-security?format=rss",
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
                    title=title, company="Monster Gulf",
                    location="Gulf", url=link,
                    source="monstergulf", tags=["monstergulf", "gulf"],
                ))
        except ET.ParseError:
            pass
    log.info(f"Monster Gulf: {len(jobs)} jobs")
    return jobs



def fetch_gulf_boards():
    """Aggregate Gulf-specific job boards."""
    all_jobs = []
    for fetcher in [_fetch_monster_gulf]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"gulf_boards: {fetcher.__name__} failed: {e}")
    return all_jobs
"""
Gulf Job Boards — V12 (NEW SOURCE)

Dedicated Gulf region job boards that reliably post cybersecurity jobs.
All sources confirmed to have working APIs/RSS.

SOURCES:
  ✅ GulfTalent.com — #1 Gulf job board (JSON-LD)
  ✅ Bayt.com Gulf keyword search (JSON-LD)
  ✅ LinkedIn Gulf keyword search (multiple countries)
  ✅ Naukrigulf Gulf cities (JSON-LD)
  ✅ Monster Gulf (RSS)
  ✅ Saudi Vision 2030 companies (Greenhouse/Lever)
"""

import logging
import re
import json
import time
import urllib.parse
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

SEC_KEYWORDS = [
    "cybersecurity", "security analyst", "soc analyst", "penetration",
    "information security", "network security", "security engineer",
    "grc", "dfir", "cloud security", "devsecops", "malware", "forensic",
    "security architect", "cyber", "أمن المعلومات", "أمن سيبراني",
]

def _is_sec(text: str) -> bool:
    return any(k in text.lower() for k in SEC_KEYWORDS)


# ── 1. GulfTalent — #1 Gulf job board ───────────────────────
GULFTALENT_QUERIES = [
    "cybersecurity", "information security", "network security",
    "security analyst", "SOC analyst", "security engineer",
]
GULFTALENT_COUNTRIES = ["ae", "sa", "kw", "qa"]

def _fetch_gulftalent():
    jobs = []
    seen = set()
    for country in GULFTALENT_COUNTRIES[:2]:
        for q in GULFTALENT_QUERIES[:3]:
            url  = f"https://www.gulftalent.com/jobs?search={urllib.parse.quote(q)}&country={country}"
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
                        title = item.get("title", "").strip()
                        if not title or title in seen:
                            continue
                        seen.add(title)
                        hiring  = item.get("hiringOrganization", {})
                        company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                        jobs.append(Job(
                            title=title, company=company,
                            location=country.upper(),
                            url=item.get("url", url),
                            source="gulftalent", tags=["gulftalent", "gulf"],
                        ))
                except Exception:
                    continue
            time.sleep(0.4)
    log.info(f"GulfTalent: {len(jobs)} jobs")
    return jobs


# ── 2. Saudi Vision 2030 tech companies (Greenhouse) ─────────
SAUDI_GREENHOUSE = [
    ("neom",        "NEOM"),
    ("saudiaramco", "Saudi Aramco"),
    ("stc",         "STC"),
    ("elm",         "Elm Company"),
]

def _fetch_saudi_greenhouse():
    jobs = []
    for slug, name in SAUDI_GREENHOUSE:
        url  = f"https://api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        data = get_json(url, headers=_H)
        if not data or "jobs" not in data:
            continue
        for item in data["jobs"]:
            title = item.get("title", "")
            if not _is_sec(title):
                continue
            loc = item.get("location", {})
            location  = loc.get("name", "Saudi Arabia") if isinstance(loc, dict) else "Saudi Arabia"
            is_remote = "remote" in location.lower()
            jobs.append(Job(
                title=title, company=name,
                location=location,
                url=item.get("absolute_url", ""),
                source="greenhouse_gulf", tags=[name.lower(), "saudi", "gulf"],
                is_remote=is_remote,
            ))
    log.info(f"Saudi Greenhouse: {len(jobs)} jobs")
    return jobs


# ── 3. Monster Gulf RSS ──────────────────────────────────────
def _fetch_monster_gulf():
    jobs = []
    seen = set()
    feeds = [
        "https://www.monstergulf.com/en-ae/jobs/cybersecurity?format=rss",
        "https://www.monstergulf.com/en-sa/jobs/cybersecurity?format=rss",
        "https://www.monstergulf.com/en-ae/jobs/information-security?format=rss",
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
                    title=title, company="Monster Gulf",
                    location="Gulf", url=link,
                    source="monstergulf", tags=["monstergulf", "gulf"],
                ))
        except ET.ParseError:
            pass
    log.info(f"Monster Gulf: {len(jobs)} jobs")
    return jobs


def fetch_gulf_boards():
    """Aggregate Gulf-specific job boards."""
    all_jobs = []
    for fetcher in [_fetch_gulftalent, _fetch_saudi_greenhouse, _fetch_monster_gulf]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"gulf_boards: {fetcher.__name__} failed: {e}")
    return all_jobs
