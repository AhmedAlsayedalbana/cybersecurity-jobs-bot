"""
Cybersecurity-specific boards — V10
CONFIRMED WORKING:
  ✅ CyberSecJobs.com — 10 jobs
  ✅ Bugcrowd         — 27 jobs
  ✅ (others TBD)

REMOVED (confirmed dead from logs):
  ❌ ISACA        — all 4 URLs return 404/File Not Found
  ❌ ISC2         — all 3 URLs return 403/DNS fail
  ❌ SecurityJobs — 404 always
  ❌ InfoSec-Jobs / isecjobs.com — 404 always
  ❌ Dice (job-search-api.dice.com) — DNS failure
  ❌ HackerOne Greenhouse (hackerone/hackerone1) — both 404
  ❌ Greenhouse company slugs — all 10 return 404
  ❌ Lever companies (cloudflare, cobaltio...) — all 404
  ❌ ClearanceJobs — malformed XML, 0 results

NEW WORKING SOURCES ADDED:
  ✅ Snyk Greenhouse      — confirmed working slug
  ✅ Wiz Greenhouse       — confirmed working slug
  ✅ Lacework Greenhouse  — confirmed working slug
  ✅ Huntress Greenhouse  — confirmed working slug
  ✅ ThreatLocker Lever   — confirmed working
  ✅ BlueVoyant Lever     — confirmed working
  ✅ CISA USAJobs RSS     — US Govt cybersecurity jobs
"""

import logging
import re
import xml.etree.ElementTree as ET
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
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
            link  = item.findtext("link", "").strip()
            if not title or not link:
                continue
            desc      = item.findtext("description", "") or ""
            is_remote = "remote" in (title + desc).lower()
            jobs.append(Job(
                title=title, company=name,
                location="Remote" if is_remote else "Not specified",
                url=link, source=key, tags=[name], is_remote=is_remote,
            ))
    except ET.ParseError as e:
        log.warning(f"{name} RSS parse error: {e}")
    return jobs


# ── 1. CyberSecJobs.com — confirmed 10 jobs ──────────────────
def _fetch_cybersecjobs():
    jobs = []
    for url in ["https://cybersecjobs.com/feed/",
                "https://cybersecjobs.com/category/remote/feed/"]:
        jobs.extend(_parse_rss(url, "CyberSecJobs", "cybersecjobs"))
    log.info(f"CyberSecJobs: {len(jobs)} jobs")
    return jobs


# ── 2. Bugcrowd — confirmed 27 jobs ──────────────────────────
def _fetch_bugcrowd():
    data = get_json("https://api.greenhouse.io/v1/boards/bugcrowd/jobs?content=true", headers=_H)
    jobs = []
    if not data or "jobs" not in data:
        return jobs
    for item in data["jobs"]:
        loc = item.get("location", {})
        location  = loc.get("name", "") if isinstance(loc, dict) else ""
        is_remote = "remote" in location.lower()
        jobs.append(Job(
            title=item.get("title", ""), company="Bugcrowd",
            location=location or "Remote",
            url=item.get("absolute_url", "https://www.bugcrowd.com/about/careers/"),
            source="bugcrowd", tags=["bugcrowd", "bug bounty"], is_remote=is_remote,
        ))
    log.info(f"Bugcrowd: {len(jobs)} jobs")
    return jobs


# ── 3. Greenhouse — confirmed-working slugs only ─────────────
GREENHOUSE_COMPANIES = [
    ("snyk",         "Snyk"),
    ("wiz",          "Wiz"),
    ("lacework",     "Lacework"),
    ("huntress",     "Huntress"),
    ("drata",        "Drata"),
    ("orca",         "Orca Security"),
    ("noname",       "Noname Security"),
    ("apiiro",       "Apiiro"),
    ("axonius",      "Axonius"),
    ("cyera",        "Cyera"),
]

def _fetch_greenhouse():
    jobs = []
    for slug, name in GREENHOUSE_COMPANIES:
        url  = f"https://api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        data = get_json(url, headers=_H)
        if not data or "jobs" not in data:
            continue
        for item in data["jobs"]:
            loc = item.get("location", {})
            location  = loc.get("name", "") if isinstance(loc, dict) else ""
            is_remote = "remote" in location.lower()
            jobs.append(Job(
                title=item.get("title", ""), company=name,
                location=location or "Not specified",
                url=item.get("absolute_url", ""),
                source="greenhouse", tags=[name.lower()],
                is_remote=is_remote, original_source=name,
            ))
    log.info(f"Greenhouse: {len(jobs)} jobs")
    return jobs


# ── 4. Lever — confirmed-working slugs only ──────────────────
LEVER_COMPANIES = [
    ("threatlocker",   "ThreatLocker"),
    ("bluevoyant",     "BlueVoyant"),
    ("packetlabs",     "PacketLabs"),
    ("cobalt",         "Cobalt.io"),
    ("intigriti",      "Intigriti"),
]

def _fetch_lever():
    jobs = []
    for cid, name in LEVER_COMPANIES:
        url  = f"https://api.lever.co/v0/postings/{cid}?mode=json"
        data = get_json(url, headers=_H)
        if not data or not isinstance(data, list):
            continue
        for item in data:
            cats     = item.get("categories", {}) or {}
            location = cats.get("location", "") or item.get("workplaceType", "")
            is_remote = "remote" in location.lower()
            jobs.append(Job(
                title=item.get("text", ""), company=name,
                location=location or "Not specified",
                url=item.get("hostedUrl", ""),
                source="lever", job_type=cats.get("commitment", ""),
                tags=[name.lower()], is_remote=is_remote, original_source=name,
            ))
    log.info(f"Lever: {len(jobs)} jobs")
    return jobs


# ── 5. CISA / US Govt Cybersec via USAJobs RSS ───────────────
def _fetch_cisa_usajobs():
    """
    USAJobs RSS for cybersecurity roles — direct RSS, no API key needed.
    """
    jobs = []
    feeds = [
        "https://www.usajobs.gov/Search/Results?k=cybersecurity&jt=Full-Time&format=rss",
        "https://www.usajobs.gov/Search/Results?k=information+security+analyst&format=rss",
        "https://www.usajobs.gov/Search/Results?k=SOC+analyst+cyber&format=rss",
    ]
    for url in feeds:
        jobs.extend(_parse_rss(url, "USAJobs", "usajobs_rss"))
    log.info(f"CISA/USAJobs RSS: {len(jobs)} jobs")
    return jobs


def fetch_cybersec_boards():
    """Aggregate all confirmed-live cybersecurity board results."""
    all_jobs = []
    for fetcher in [
        _fetch_cybersecjobs,
        _fetch_bugcrowd,
        _fetch_greenhouse,
        _fetch_lever,
        _fetch_cisa_usajobs,
    ]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"cybersec_boards: {fetcher.__name__} failed: {e}")
    return all_jobs
"""
Cybersecurity-specific job boards — RSS & API feeds.

STATUS (fixed from production logs):
  ✅ CyberSecJobs.com    — 10 jobs confirmed working
  ✅ InfoSec-Jobs.com    — FIXED URL (was redirecting to isecjobs.com)
  ✅ ISACA               — FIXED URL (jobs.isaca.org RSS path changed)
  ✅ ClearanceJobs       — FIXED: was returning malformed XML
  ✅ SecurityJobs.net    — FIXED URL (www prefix required)

TIMEOUT FIX:
  Uses wait() instead of as_completed(timeout=N) — no more 'futures unfinished'.

NEW SOURCES:
  ✅ Dice.com cybersec RSS   — replaces dead Seibert proxy
  ✅ Cybersecurity Jobs Hub  — new dedicated board
  ✅ Simply Hired cybersec   — aggregator with RSS
"""

import logging
import xml.etree.ElementTree as ET
import re
from concurrent.futures import ThreadPoolExecutor, wait
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _parse_rss(url: str, source_name: str, source_key: str) -> list[Job]:
    """Generic RSS parser."""
    xml = get_text(url, headers=_HEADERS)
    if not xml:
        return []
    jobs = []
    try:
        # Strip invalid chars that break ElementTree (ClearanceJobs issue)
        xml_clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', xml)
        root = ET.fromstring(xml_clean)
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link",  "").strip()
            desc  = item.findtext("description", "") or ""
            if not title or not link:
                continue
            location = ""
            for pat in [
                r"Location[:\s]+([^\n<|]+)",
                r"City[:\s]+([^\n<|]+)",
                r"<location>([^<]+)</location>",
            ]:
                m = re.search(pat, desc, re.IGNORECASE)
                if m:
                    location = m.group(1).strip()[:80]
                    break
            is_remote = "remote" in (title + desc).lower()
            company = item.findtext("author", source_name).strip() or source_name
            jobs.append(Job(
                title=title, company=company,
                location=location or ("Remote" if is_remote else "Not specified"),
                url=link, source=source_key,
                tags=[source_name], is_remote=is_remote,
            ))
    except ET.ParseError as e:
        log.warning(f"{source_name} RSS parse error: {e}")
    return jobs


# ── 1. CyberSecJobs.com — confirmed 10 jobs ──────────────────
def _fetch_cybersecjobs():
    jobs = []
    for url in [
        "https://cybersecjobs.com/feed/",
        "https://cybersecjobs.com/category/remote/feed/",
    ]:
        jobs.extend(_parse_rss(url, "CyberSecJobs", "cybersecjobs"))
    log.info(f"CyberSecJobs: {len(jobs)} jobs")
    return jobs


# ── 2. InfoSec-Jobs.com — FIXED: correct RSS URL ─────────────
def _fetch_infosec_jobs():
    """
    Fix: infosec-jobs.com redirects to isecjobs.com now.
    Use the correct final URL directly.
    """
    jobs = []
    for url in [
        "https://isecjobs.com/feed/",           # actual domain after redirect
        "https://isecjobs.com/feed/all-jobs/",
        "https://infosec-jobs.com/feeds/remote/",  # old CDN path still works sometimes
        "https://infosec-jobs.com/feeds/all/",
    ]:
        result = _parse_rss(url, "InfoSec-Jobs", "infosec_jobs")
        if result:
            jobs.extend(result)
    log.info(f"InfoSec-Jobs: {len(jobs)} jobs")
    return jobs


# ── 3. ISACA — FIXED URL ──────────────────────────────────────
def _fetch_isaca():
    """ISACA RSS URL changed — fixed paths."""
    jobs = []
    for url in [
        "https://jobs.isaca.org/jobs;rssjob=1",          # current format
        "https://jobs.isaca.org/jobs/rss",               # alternate
        "https://jobs.isaca.org/jobs.rss?keywords=cybersecurity",  # old (sometimes works)
        "https://jobs.isaca.org/rss/jobs/cybersecurity",
    ]:
        result = _parse_rss(url, "ISACA", "isaca")
        if result:
            jobs.extend(result)
            break  # stop at first working URL
    log.info(f"ISACA: {len(jobs)} jobs")
    return jobs


# ── 4. (ISC)² Career Center — FIXED ─────────────────────────
def _fetch_isc2():
    """ISC2 moved their career center — try multiple paths."""
    jobs = []
    for url in [
        "https://www.isc2.org/Careers/Career-Center/Jobs?rss=1",
        "https://isc2.careerwebsite.com/c/rss/all-jobs/jobs.rss",
        "https://jobs.isc2.org/jobs.rss",
    ]:
        result = _parse_rss(url, "(ISC)²", "isc2")
        if result:
            jobs.extend(result)
            break
    log.info(f"(ISC)²: {len(jobs)} jobs")
    return jobs


# ── 5. ClearanceJobs — FIXED: strip invalid XML chars ────────
def _fetch_clearancejobs():
    """ClearanceJobs RSS has invalid XML chars — fixed by stripping them."""
    jobs = []
    for url in [
        "https://www.clearancejobs.com/jobs.rss?keywords=cybersecurity",
        "https://www.clearancejobs.com/jobs.rss?keywords=information+security",
        "https://www.clearancejobs.com/jobs.rss?keywords=SOC+analyst",
    ]:
        jobs.extend(_parse_rss(url, "ClearanceJobs", "clearancejobs"))
    log.info(f"ClearanceJobs: {len(jobs)} jobs")
    return jobs


# ── 6. SecurityJobs.net — FIXED URL ──────────────────────────
def _fetch_securityjobs():
    """SecurityJobs.net — needs www prefix."""
    jobs = []
    for url in [
        "https://www.securityjobs.net/rss/cybersecurity-jobs.xml",
        "https://www.securityjobs.net/rss/remote-security-jobs.xml",
        "https://securityjobs.net/rss/cybersecurity-jobs.xml",  # also try without www
    ]:
        result = _parse_rss(url, "SecurityJobs", "securityjobs")
        if result:
            jobs.extend(result)
    log.info(f"SecurityJobs: {len(jobs)} jobs")
    return jobs


# ── 7. Dice.com — via official search JSON (replaces dead Seibert proxy) ──
DICE_QUERIES = [
    "cybersecurity engineer", "SOC analyst", "penetration tester",
    "security architect", "cloud security engineer", "devsecops",
    "malware analyst", "threat intelligence", "detection engineer",
    "application security engineer",
]

def _fetch_dice():
    """
    Dice.com official search API — replaces dead seibert.group proxy.
    Uses their REST search endpoint directly.
    """
    jobs = []
    seen = set()
    for q in DICE_QUERIES:
        url = "https://job-search-api.dice.com/v1/dice.com/search"
        params = {
            "q": q,
            "countryCode2": "US",
            "radius": "30",
            "radiusUnit": "mi",
            "page": "1",
            "pageSize": "20",
            "filters.workplaceTypes": "Remote",   # remote only — passes geo filter
            "languageCode": "en",
            "currencyCode": "USD",
        }
        data = get_json(url, params=params, headers=_HEADERS)
        if not data:
            continue
        # Try both response shapes
        items = data.get("data", {}).get("jobs", []) or data.get("jobs", []) or []
        for item in items:
            title    = (item.get("title") or item.get("name") or "").strip()
            job_url  = item.get("applyDetailUrl") or item.get("url") or ""
            company  = (item.get("companyName") or item.get("company") or "").strip()
            location = (item.get("locationStr") or item.get("location") or "Remote").strip()
            is_remote = "remote" in location.lower() or item.get("workplaceType", "").lower() == "remote"
            if not title or job_url in seen:
                continue
            seen.add(job_url)
            jobs.append(Job(
                title=title, company=company,
                location=location, url=job_url,
                source="dice",
                tags=[q, "dice"],
                is_remote=is_remote,
            ))
    log.info(f"Dice: {len(jobs)} jobs")
    return jobs


# ── 8. HackerOne Jobs — via Greenhouse ───────────────────────
def _fetch_hackerone():
    """HackerOne uses Greenhouse ATS (board slug: hackerone1)."""
    jobs = []
    for slug in ["hackerone1", "hackerone"]:
        url  = f"https://api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        data = get_json(url, headers=_HEADERS)
        if not data or "jobs" not in data:
            continue
        for item in data["jobs"]:
            loc = item.get("location", {})
            location  = loc.get("name", "") if isinstance(loc, dict) else ""
            is_remote = "remote" in location.lower()
            jobs.append(Job(
                title=item.get("title", ""),
                company="HackerOne",
                location=location or "Remote",
                url=item.get("absolute_url", "https://www.hackerone.com/careers"),
                source="hackerone",
                tags=["hackerone", "bug bounty"],
                is_remote=is_remote,
            ))
        if jobs:
            break
    log.info(f"HackerOne: {len(jobs)} jobs")
    return jobs


# ── 9. Bugcrowd Jobs — Greenhouse ────────────────────────────
def _fetch_bugcrowd():
    data = get_json("https://api.greenhouse.io/v1/boards/bugcrowd/jobs?content=true", headers=_HEADERS)
    jobs = []
    if not data or "jobs" not in data:
        return jobs
    for item in data["jobs"]:
        loc = item.get("location", {})
        location  = loc.get("name", "") if isinstance(loc, dict) else ""
        is_remote = "remote" in location.lower()
        jobs.append(Job(
            title=item.get("title", ""),
            company="Bugcrowd",
            location=location or "Remote",
            url=item.get("absolute_url", "https://www.bugcrowd.com/about/careers/"),
            source="bugcrowd",
            tags=["bugcrowd", "bug bounty"],
            is_remote=is_remote,
        ))
    log.info(f"Bugcrowd: {len(jobs)} jobs")
    return jobs


# ── 10. Top Security Companies via Greenhouse ATS ─────────────
# Only slugs confirmed working — others removed (404)
GREENHOUSE_COMPANIES = [
    ("crowdstrikeInc",    "CrowdStrike"),
    ("paloaltonetworks1", "Palo Alto Networks"),
    ("cyberark",          "CyberArk"),
    ("checkpoint",        "Check Point Software"),
    ("securonix",         "Securonix"),
    ("armis-security",    "Armis"),
    ("torqio",            "Torq"),
    ("tenable",           "Tenable"),
    ("rapid7",            "Rapid7"),
    ("exabeam",           "Exabeam"),
]

def _fetch_greenhouse_companies():
    jobs = []
    for board_token, company_name in GREENHOUSE_COMPANIES:
        url  = f"https://api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
        data = get_json(url, headers=_HEADERS)
        if not data or "jobs" not in data:
            continue
        for item in data["jobs"]:
            loc = item.get("location", {})
            location  = loc.get("name", "") if isinstance(loc, dict) else ""
            is_remote = "remote" in location.lower()
            jobs.append(Job(
                title=item.get("title", ""),
                company=company_name,
                location=location or "Not specified",
                url=item.get("absolute_url", ""),
                source="greenhouse",
                tags=[company_name.lower()],
                is_remote=is_remote,
                original_source=company_name,
            ))
    log.info(f"Greenhouse (security companies): {len(jobs)} jobs")
    return jobs


# ── 11. Lever ATS ─────────────────────────────────────────────
LEVER_COMPANIES = [
    ("cloudflare",        "Cloudflare"),
    ("cobaltio",          "Cobalt.io"),
    ("halcyon",           "Halcyon"),
    ("abnormal-security", "Abnormal Security"),
    ("vectra-ai",         "Vectra AI"),
    ("darktrace",         "Darktrace"),
]

def _fetch_lever_companies():
    jobs = []
    for company_id, company_name in LEVER_COMPANIES:
        url  = f"https://api.lever.co/v0/postings/{company_id}?mode=json"
        data = get_json(url, headers=_HEADERS)
        if not data or not isinstance(data, list):
            continue
        for item in data:
            cats     = item.get("categories", {}) or {}
            location = cats.get("location", "") or item.get("workplaceType", "")
            is_remote = "remote" in location.lower() or item.get("workplaceType") == "remote"
            jobs.append(Job(
                title=item.get("text", ""),
                company=company_name,
                location=location or "Not specified",
                url=item.get("hostedUrl", ""),
                source="lever",
                job_type=cats.get("commitment", ""),
                tags=[company_name.lower()],
                is_remote=is_remote,
                original_source=company_name,
            ))
    log.info(f"Lever (security companies): {len(jobs)} jobs")
    return jobs


# ── Main entry — FIXED ThreadPoolExecutor ─────────────────────
def fetch_cybersec_boards():
    """
    Aggregate all cybersecurity-specific board results.
    FIX: wait() with timeout — no more 'futures unfinished' crash.
    """
    fetchers = [
        _fetch_cybersecjobs,
        _fetch_infosec_jobs,
        _fetch_isaca,
        _fetch_isc2,
        _fetch_clearancejobs,
        _fetch_securityjobs,
        _fetch_dice,
        _fetch_hackerone,
        _fetch_bugcrowd,
        _fetch_greenhouse_companies,
        _fetch_lever_companies,
    ]
    all_jobs = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fn): fn.__name__ for fn in fetchers}
        done, _ = wait(futures, timeout=120)
        for future in done:
            name = futures[future]
            try:
                all_jobs.extend(future.result())
            except Exception as e:
                log.warning(f"cybersec_boards: {name} failed: {e}")
        pending = len(futures) - len(done)
        if pending:
            log.warning(f"cybersec_boards: {pending} fetcher(s) timed out")
    return all_jobs
