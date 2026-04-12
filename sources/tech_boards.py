"""
General tech boards and ATS with strong security coverage:
  - Dice.com (tech-focused)
  - BugCrowd Jobs (bug bounty platform)
  - HackerOne Jobs (bug bounty platform)
  - Greenhouse ATS (top security companies)
  - Lever ATS (security companies)
No API keys required.
"""

import logging
import xml.etree.ElementTree as ET
import re
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _parse_rss(url: str, source_name: str, source_key: str) -> list[Job]:
    xml = get_text(url, headers=HEADERS)
    if not xml:
        return []
    jobs = []
    try:
        root = ET.fromstring(xml)
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link",  "").strip()
            desc  = item.findtext("description", "") or ""
            if not title or not link:
                continue
            location = ""
            m = re.search(r"(?:Location|location)[:\s]+([^\n<|]+)", desc)
            if m:
                location = m.group(1).strip()[:80]
            is_remote = "remote" in (title + desc).lower()
            jobs.append(Job(
                title=title,
                company=source_name,
                location=location or ("Remote" if is_remote else "Not specified"),
                url=link,
                source=source_key,
                tags=[source_name],
                is_remote=is_remote,
            ))
    except ET.ParseError as e:
        log.warning(f"{source_name} RSS parse error: {e}")
    return jobs


# ── Dice.com ──────────────────────────────────────────────────
DICE_QUERIES = [
    "cybersecurity engineer", "penetration tester", "SOC analyst",
    "information security analyst", "cloud security engineer",
    "application security engineer", "devsecops", "security architect",
    "malware analyst", "threat intelligence analyst", "detection engineer",
]


def _fetch_dice() -> list[Job]:
    """
    The seibert.group proxy for Dice is dead (DNS failure).
    Use Dice's own search API directly.
    """
    import json
    jobs = []
    seen = set()

    for q in DICE_QUERIES:
        # Dice has a public search API at this endpoint
        url = "https://job-search-api.dice.com/v1/jobs/search"
        params = {
            "q": q,
            "countryCode2": "US",
            "pageSize": "20",
            "sort": "-postedDate",
        }
        data = get_json(url, params=params, headers={
            **HEADERS,
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.dice.com",
            "Referer": "https://www.dice.com/",
        })

        if not data:
            # Fallback: scrape Dice search page for JSON-LD
            page_url = f"https://www.dice.com/jobs?q={q.replace(' ', '+')}&sort=postedDate"
            html = get_text(page_url, headers=HEADERS)
            if html:
                for block in re.findall(
                    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                    html, re.DOTALL | re.IGNORECASE
                ):
                    try:
                        item = json.loads(block.strip())
                        if item.get("@type") != "JobPosting":
                            continue
                        title = item.get("title", "").strip()
                        link = item.get("url", page_url)
                        if not title or link in seen:
                            continue
                        seen.add(link)
                        loc = item.get("jobLocation", {})
                        if isinstance(loc, dict):
                            addr = loc.get("address", {})
                            location = addr.get("addressLocality", "") or addr.get("addressRegion", "")
                        else:
                            location = "US"
                        jobs.append(Job(
                            title=title,
                            company=item.get("hiringOrganization", {}).get("name", "Unknown"),
                            location=location or "US",
                            url=link,
                            source="dice",
                            tags=[q],
                            is_remote="remote" in (title + str(item)).lower(),
                        ))
                    except (json.JSONDecodeError, KeyError, AttributeError):
                        continue
            continue

        for item in (data.get("data") or data.get("hits") or []):
            location = item.get("locationStr", "") or item.get("location", "")
            is_remote = (
                item.get("workFromHomeAvailability", "") in ("REMOTE", "FULLTIME_REMOTE")
                or "remote" in location.lower()
            )
            link = (
                item.get("apply", {}).get("applyUrl", "")
                or f"https://www.dice.com/jobs/detail/{item.get('id', '')}"
            )
            if not item.get("title") or link in seen:
                continue
            seen.add(link)
            jobs.append(Job(
                title=item.get("title", ""),
                company=item.get("hiringCompany", {}).get("name", "") or item.get("company", ""),
                location=location or ("Remote" if is_remote else "Not specified"),
                url=link,
                source="dice",
                salary=item.get("salary", ""),
                job_type=item.get("employmentType", ""),
                tags=[q],
                is_remote=is_remote,
            ))
    log.info(f"Dice: {len(jobs)} jobs")
    return jobs


# ── BugCrowd Jobs ─────────────────────────────────────────────
def _fetch_bugcrowd() -> list[Job]:
    url = "https://api.greenhouse.io/v1/boards/bugcrowd/jobs?content=true"
    data = get_json(url, headers=HEADERS)
    jobs = []
    if not data or "jobs" not in data:
        return jobs
    for item in data["jobs"]:
        location = item.get("location", {}).get("name", "")
        is_remote = "remote" in location.lower()
        jobs.append(Job(
            title=item.get("title", ""),
            company="Bugcrowd",
            location=location or "Not specified",
            url=item.get("absolute_url", "https://www.bugcrowd.com/about/careers/"),
            source="bugcrowd",
            tags=["bugcrowd", "bug bounty"],
            is_remote=is_remote,
        ))
    log.info(f"Bugcrowd: {len(jobs)} jobs")
    return jobs


# ── HackerOne Jobs ────────────────────────────────────────────
def _fetch_hackerone() -> list[Job]:
    url = "https://api.greenhouse.io/v1/boards/hackerone1/jobs?content=true"
    data = get_json(url, headers=HEADERS)
    jobs = []
    if not data or "jobs" not in data:
        return jobs
    for item in data["jobs"]:
        location = item.get("location", {}).get("name", "")
        is_remote = "remote" in location.lower()
        jobs.append(Job(
            title=item.get("title", ""),
            company="HackerOne",
            location=location or "Not specified",
            url=item.get("absolute_url", "https://www.hackerone.com/careers"),
            source="hackerone",
            tags=["hackerone", "bug bounty"],
            is_remote=is_remote,
        ))
    log.info(f"HackerOne: {len(jobs)} jobs")
    return jobs


# ── Top Security Companies via Greenhouse ATS ─────────────────
GREENHOUSE_COMPANIES = [
    ("crowdstrikeInc",   "CrowdStrike"),
    ("paloaltonetworks1", "Palo Alto Networks"),
    ("sentinelone",      "SentinelOne"),
    # ("snyk",             "Snyk"),  # moved to Workday ATS
    ("wiz",              "Wiz"),
    # ("orca-security",    "Orca Security"),  # moved ATS
    ("tenable",          "Tenable"),
    ("rapid7",           "Rapid7"),
    # ("lacework",         "Lacework"),  # acquired by Fortinet
    ("exabeam",          "Exabeam"),
    # Additional verified working board tokens
    ("torqio",           "Torq"),
    ("armis-security",   "Armis"),
    ("cyberark",         "CyberArk"),
    ("checkpoint",       "Check Point Software"),
    ("securonix",        "Securonix"),
]


def _fetch_greenhouse_companies() -> list[Job]:
    jobs = []
    for board_token, company_name in GREENHOUSE_COMPANIES:
        url = f"https://api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
        data = get_json(url, headers=HEADERS)
        if not data or "jobs" not in data:
            continue
        for item in data["jobs"]:
            location = item.get("location", {}).get("name", "")
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


# ── Lever ATS (security companies) ───────────────────────────
LEVER_COMPANIES = [
    # Verified working Lever board slugs (2025)
    ("cloudflare",      "Cloudflare"),       # moved to greenhouse but keep trying
    ("cobaltio",        "Cobalt.io"),         # slug changed from cobalt-io
    ("bugcrowd",        "Bugcrowd"),
    ("halcyon",         "Halcyon"),
    ("abnormal-security", "Abnormal Security"),
    ("vectra-ai",       "Vectra AI"),
    ("darktrace",       "Darktrace"),
]


def _fetch_lever_companies() -> list[Job]:
    jobs = []
    for company_id, company_name in LEVER_COMPANIES:
        url = f"https://api.lever.co/v0/postings/{company_id}?mode=json"
        data = get_json(url, headers=HEADERS)
        if not data or not isinstance(data, list):
            continue
        for item in data:
            cats = item.get("categories", {}) or {}
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


def fetch_tech_boards() -> list[Job]:
    """Aggregate all tech board results."""
    jobs = []
    for fetcher in [
        _fetch_dice,
        _fetch_bugcrowd,
        _fetch_hackerone,
        _fetch_greenhouse_companies,
        _fetch_lever_companies,
    ]:
        try:
            jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"TechBoard sub-fetcher {fetcher.__name__} failed: {e}")
    return jobs
"""
General tech boards and ATS with strong security coverage:
  - Dice.com (tech-focused)
  - BugCrowd Jobs (bug bounty platform)
  - HackerOne Jobs (bug bounty platform)
  - Greenhouse ATS (top security companies)
  - Lever ATS (security companies)
No API keys required.
"""

import logging
import xml.etree.ElementTree as ET
import re
from models import Job
from sources.http_utils import get_text, get_json

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _parse_rss(url: str, source_name: str, source_key: str) -> list[Job]:
    xml = get_text(url, headers=HEADERS)
    if not xml:
        return []
    jobs = []
    try:
        root = ET.fromstring(xml)
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link",  "").strip()
            desc  = item.findtext("description", "") or ""
            if not title or not link:
                continue
            location = ""
            m = re.search(r"(?:Location|location)[:\s]+([^\n<|]+)", desc)
            if m:
                location = m.group(1).strip()[:80]
            is_remote = "remote" in (title + desc).lower()
            jobs.append(Job(
                title=title,
                company=source_name,
                location=location or ("Remote" if is_remote else "Not specified"),
                url=link,
                source=source_key,
                tags=[source_name],
                is_remote=is_remote,
            ))
    except ET.ParseError as e:
        log.warning(f"{source_name} RSS parse error: {e}")
    return jobs


# ── Dice.com ──────────────────────────────────────────────────
DICE_QUERIES = [
    "cybersecurity engineer", "penetration tester", "SOC analyst",
    "information security analyst", "cloud security engineer",
    "application security engineer", "devsecops", "security architect",
    "malware analyst", "threat intelligence analyst", "detection engineer",
]


def _fetch_dice() -> list[Job]:
    jobs = []
    for q in DICE_QUERIES:
        url = (
            "https://job-search-api.seibert.group/v1/dice/jobs"
            f"?q={q.replace(' ', '%20')}&countryCode=US&pageSize=20&sort=updated"
        )
        data = get_json(url, headers=HEADERS)
        if not data or "data" not in data:
            continue
        for item in data["data"]:
            location = item.get("locationStr", "") or item.get("location", "")
            is_remote = (
                item.get("workFromHomeAvailability", "") in ("REMOTE", "FULLTIME_REMOTE")
                or "remote" in location.lower()
            )
            jobs.append(Job(
                title=item.get("title", ""),
                company=item.get("hiringCompany", {}).get("name", "") or item.get("company", ""),
                location=location or ("Remote" if is_remote else "Not specified"),
                url=(
                    item.get("apply", {}).get("applyUrl", "")
                    or f"https://www.dice.com/jobs/detail/{item.get('id', '')}"
                ),
                source="dice",
                salary=item.get("salary", ""),
                job_type=item.get("employmentType", ""),
                tags=[q],
                is_remote=is_remote,
            ))
    log.info(f"Dice: {len(jobs)} jobs")
    return jobs


# ── BugCrowd Jobs ─────────────────────────────────────────────
def _fetch_bugcrowd() -> list[Job]:
    url = "https://api.greenhouse.io/v1/boards/bugcrowd/jobs?content=true"
    data = get_json(url, headers=HEADERS)
    jobs = []
    if not data or "jobs" not in data:
        return jobs
    for item in data["jobs"]:
        location = item.get("location", {}).get("name", "")
        is_remote = "remote" in location.lower()
        jobs.append(Job(
            title=item.get("title", ""),
            company="Bugcrowd",
            location=location or "Not specified",
            url=item.get("absolute_url", "https://www.bugcrowd.com/about/careers/"),
            source="bugcrowd",
            tags=["bugcrowd", "bug bounty"],
            is_remote=is_remote,
        ))
    log.info(f"Bugcrowd: {len(jobs)} jobs")
    return jobs


# ── HackerOne Jobs ────────────────────────────────────────────
def _fetch_hackerone() -> list[Job]:
    url = "https://api.greenhouse.io/v1/boards/hackerone/jobs?content=true"
    data = get_json(url, headers=HEADERS)
    jobs = []
    if not data or "jobs" not in data:
        return jobs
    for item in data["jobs"]:
        location = item.get("location", {}).get("name", "")
        is_remote = "remote" in location.lower()
        jobs.append(Job(
            title=item.get("title", ""),
            company="HackerOne",
            location=location or "Not specified",
            url=item.get("absolute_url", "https://www.hackerone.com/careers"),
            source="hackerone",
            tags=["hackerone", "bug bounty"],
            is_remote=is_remote,
        ))
    log.info(f"HackerOne: {len(jobs)} jobs")
    return jobs


# ── Top Security Companies via Greenhouse ATS ─────────────────
GREENHOUSE_COMPANIES = [
    ("crowdstrike",      "CrowdStrike"),
    ("paloaltonetworks", "Palo Alto Networks"),
    ("sentinelone",      "SentinelOne"),
    ("snyk",             "Snyk"),
    ("wiz-inc",          "Wiz"),
    ("orca-security",    "Orca Security"),
    ("tenable",          "Tenable"),
    ("rapid7",           "Rapid7"),
    ("lacework",         "Lacework"),
    ("exabeam",          "Exabeam"),
]


def _fetch_greenhouse_companies() -> list[Job]:
    jobs = []
    for board_token, company_name in GREENHOUSE_COMPANIES:
        url = f"https://api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
        data = get_json(url, headers=HEADERS)
        if not data or "jobs" not in data:
            continue
        for item in data["jobs"]:
            location = item.get("location", {}).get("name", "")
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


# ── Lever ATS (security companies) ───────────────────────────
LEVER_COMPANIES = [
    ("cloudflare",  "Cloudflare"),
    ("cobalt-io",   "Cobalt.io"),
    ("intigriti",   "Intigriti"),
    ("detectify",   "Detectify"),
]


def _fetch_lever_companies() -> list[Job]:
    jobs = []
    for company_id, company_name in LEVER_COMPANIES:
        url = f"https://api.lever.co/v0/postings/{company_id}?mode=json"
        data = get_json(url, headers=HEADERS)
        if not data or not isinstance(data, list):
            continue
        for item in data:
            cats = item.get("categories", {}) or {}
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


def fetch_tech_boards() -> list[Job]:
    """Aggregate all tech board results."""
    jobs = []
    for fetcher in [
        _fetch_dice,
        _fetch_bugcrowd,
        _fetch_hackerone,
        _fetch_greenhouse_companies,
        _fetch_lever_companies,
    ]:
        try:
            jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"TechBoard sub-fetcher {fetcher.__name__} failed: {e}")
    return jobs
