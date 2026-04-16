"""
Cybersecurity-specific job boards.

REMOVED (all return 404 or timeout):
  ❌ Greenhouse slugs: snyk, wiz, lacework, drata, vanta, crowdstrike,
     sentinelone, paloaltonetworks, rapid7, tenable, secureworks,
     elastic, cyberark, recordedfuture, varonis, sailpoint, axonius,
     orca, abnormalsecurity, exabeam, huntress
  ❌ Lever slugs: 1password, bitwarden, securityscorecard, cloudflare,
     intigriti, detectify, cyberark, recordedfuture, bugcrowd, synack,
     cobalt, immunefi, wazuh

CONFIRMED WORKING:
  ❌ CyberSecJobs — 404 Not Found (REMOVED)
  ✅ Bugcrowd careers page
  ✅ HackerOne careers page
  ✅ BuiltIn security jobs
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
    "Accept-Language": "en-US,en;q=0.9",
}

SEC_KEYWORDS = [
    "security", "cyber", "soc", "pentest", "penetration", "grc",
    "forensic", "dfir", "malware", "threat", "vulnerability",
    "appsec", "devsecops", "cloud security", "red team", "blue team",
]

def _is_sec(text: str) -> bool:
    return any(k in text.lower() for k in SEC_KEYWORDS)


# ── 1. Bugcrowd Greenhouse board ─────────────────────────────
def _fetch_bugcrowd():
    jobs = []
    url  = "https://api.greenhouse.io/v1/boards/bugcrowd/jobs?content=true"
    data = get_json(url, headers=_H)
    if not data or "jobs" not in data:
        log.info("Bugcrowd: 0 jobs")
        return jobs
    for item in data["jobs"]:
        title = item.get("title", "")
        if not _is_sec(title):
            continue
        loc      = item.get("location", {})
        location = loc.get("name", "") if isinstance(loc, dict) else ""
        is_remote = "remote" in location.lower()
        jobs.append(Job(
            title=title, company="Bugcrowd",
            location=location or "Not specified",
            url=item.get("absolute_url", ""),
            source="bugcrowd", tags=["bugcrowd"],
            is_remote=is_remote, original_source="Bugcrowd",
        ))
    log.info(f"Bugcrowd: {len(jobs)} jobs")
    return jobs


# ── 3. HackerOne careers page ────────────────────────────────
def _fetch_hackerone():
    jobs = []
    seen = set()
    url  = "https://www.hackerone.com/careers"
    html = get_text(url, headers=_H)
    if not html:
        log.info("HackerOne: 0 jobs")
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
                title = item.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                hiring  = item.get("hiringOrganization", {})
                company = hiring.get("name", "HackerOne") if isinstance(hiring, dict) else "HackerOne"
                loc_obj = item.get("jobLocation", {})
                location = ""
                if isinstance(loc_obj, dict):
                    addr = loc_obj.get("address", {})
                    if isinstance(addr, dict):
                        location = addr.get("addressLocality", "")
                is_remote = bool(item.get("jobLocationType") == "TELECOMMUTE") or "remote" in location.lower()
                jobs.append(Job(
                    title=title, company=company,
                    location=location or ("Remote" if is_remote else "Not specified"),
                    url=item.get("url", url),
                    source="hackerone", tags=["hackerone"],
                    is_remote=is_remote, original_source="HackerOne",
                ))
        except Exception:
            continue
    log.info(f"HackerOne: {len(jobs)} jobs")
    return jobs


# ── 4. BuiltIn security jobs ─────────────────────────────────
def _fetch_builtin():
    jobs = []
    seen = set()
    searches = [
        "https://builtin.com/jobs/cybersecurity",
        "https://builtin.com/jobs/information-security",
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
                    title = item.get("title", "").strip()
                    if not title or title in seen or not _is_sec(title):
                        continue
                    seen.add(title)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    loc_obj = item.get("jobLocation", {})
                    location = ""
                    if isinstance(loc_obj, dict):
                        addr = loc_obj.get("address", {})
                        if isinstance(addr, dict):
                            location = addr.get("addressLocality", addr.get("addressCountry", ""))
                    is_remote = bool(item.get("jobLocationType") == "TELECOMMUTE")
                    jobs.append(Job(
                        title=title, company=company,
                        location=location or ("Remote" if is_remote else "Not specified"),
                        url=item.get("url", url),
                        source="builtin", tags=["builtin"],
                        is_remote=is_remote,
                    ))
            except Exception:
                continue
    log.info(f"BuiltIn: {len(jobs)} jobs")
    return jobs


def fetch_cybersec_boards():
    """Fetch from confirmed-live cybersecurity job boards."""
    all_jobs = []
    for fetcher in [
        _fetch_bugcrowd,
        _fetch_hackerone,
        _fetch_builtin,
    ]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"cybersec_boards: {fetcher.__name__} failed: {e}")
    return all_jobs
"""
Cybersecurity-specific job boards.

REMOVED (all return 404 or timeout):
  ❌ Greenhouse slugs: snyk, wiz, lacework, drata, vanta, crowdstrike,
     sentinelone, paloaltonetworks, rapid7, tenable, secureworks,
     elastic, cyberark, recordedfuture, varonis, sailpoint, axonius,
     orca, abnormalsecurity, exabeam, huntress
  ❌ Lever slugs: 1password, bitwarden, securityscorecard, cloudflare,
     intigriti, detectify, cyberark, recordedfuture, bugcrowd, synack,
     cobalt, immunefi, wazuh

CONFIRMED WORKING:
  ✅ CyberSecJobs.com RSS
  ✅ Bugcrowd careers page
  ✅ HackerOne careers page
  ✅ BuiltIn security jobs
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
    "Accept-Language": "en-US,en;q=0.9",
}

SEC_KEYWORDS = [
    "security", "cyber", "soc", "pentest", "penetration", "grc",
    "forensic", "dfir", "malware", "threat", "vulnerability",
    "appsec", "devsecops", "cloud security", "red team", "blue team",
]

def _is_sec(text: str) -> bool:
    return any(k in text.lower() for k in SEC_KEYWORDS)


# ── 1. Bugcrowd Greenhouse board ─────────────────────────────
def _fetch_bugcrowd():
    jobs = []
    url  = "https://api.greenhouse.io/v1/boards/bugcrowd/jobs?content=true"
    data = get_json(url, headers=_H)
    if not data or "jobs" not in data:
        log.info("Bugcrowd: 0 jobs")
        return jobs
    for item in data["jobs"]:
        title = item.get("title", "")
        if not _is_sec(title):
            continue
        loc      = item.get("location", {})
        location = loc.get("name", "") if isinstance(loc, dict) else ""
        is_remote = "remote" in location.lower()
        jobs.append(Job(
            title=title, company="Bugcrowd",
            location=location or "Not specified",
            url=item.get("absolute_url", ""),
            source="bugcrowd", tags=["bugcrowd"],
            is_remote=is_remote, original_source="Bugcrowd",
        ))
    log.info(f"Bugcrowd: {len(jobs)} jobs")
    return jobs


# ── 3. HackerOne careers page ────────────────────────────────
def _fetch_hackerone():
    jobs = []
    seen = set()
    url  = "https://www.hackerone.com/careers"
    html = get_text(url, headers=_H)
    if not html:
        log.info("HackerOne: 0 jobs")
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
                title = item.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                hiring  = item.get("hiringOrganization", {})
                company = hiring.get("name", "HackerOne") if isinstance(hiring, dict) else "HackerOne"
                loc_obj = item.get("jobLocation", {})
                location = ""
                if isinstance(loc_obj, dict):
                    addr = loc_obj.get("address", {})
                    if isinstance(addr, dict):
                        location = addr.get("addressLocality", "")
                is_remote = bool(item.get("jobLocationType") == "TELECOMMUTE") or "remote" in location.lower()
                jobs.append(Job(
                    title=title, company=company,
                    location=location or ("Remote" if is_remote else "Not specified"),
                    url=item.get("url", url),
                    source="hackerone", tags=["hackerone"],
                    is_remote=is_remote, original_source="HackerOne",
                ))
        except Exception:
            continue
    log.info(f"HackerOne: {len(jobs)} jobs")
    return jobs


# ── 4. BuiltIn security jobs ─────────────────────────────────
def _fetch_builtin():
    jobs = []
    seen = set()
    searches = [
        "https://builtin.com/jobs/cybersecurity",
        "https://builtin.com/jobs/information-security",
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
                    title = item.get("title", "").strip()
                    if not title or title in seen or not _is_sec(title):
                        continue
                    seen.add(title)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    loc_obj = item.get("jobLocation", {})
                    location = ""
                    if isinstance(loc_obj, dict):
                        addr = loc_obj.get("address", {})
                        if isinstance(addr, dict):
                            location = addr.get("addressLocality", addr.get("addressCountry", ""))
                    is_remote = bool(item.get("jobLocationType") == "TELECOMMUTE")
                    jobs.append(Job(
                        title=title, company=company,
                        location=location or ("Remote" if is_remote else "Not specified"),
                        url=item.get("url", url),
                        source="builtin", tags=["builtin"],
                        is_remote=is_remote,
                    ))
            except Exception:
                continue
    log.info(f"BuiltIn: {len(jobs)} jobs")
    return jobs


def fetch_cybersec_boards():
    """Fetch from confirmed-live cybersecurity job boards."""
    all_jobs = []
    for fetcher in [
        _fetch_bugcrowd,
        _fetch_hackerone,
        _fetch_builtin,
    ]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"cybersec_boards: {fetcher.__name__} failed: {e}")
    return all_jobs
"""
Cybersecurity-specific job boards.

REMOVED (all return 404 or timeout):
  ❌ Greenhouse slugs: snyk, wiz, lacework, drata, vanta, crowdstrike,
     sentinelone, paloaltonetworks, rapid7, tenable, secureworks,
     elastic, cyberark, recordedfuture, varonis, sailpoint, axonius,
     orca, abnormalsecurity, exabeam, huntress
  ❌ Lever slugs: 1password, bitwarden, securityscorecard, cloudflare,
     intigriti, detectify, cyberark, recordedfuture, bugcrowd, synack,
     cobalt, immunefi, wazuh

CONFIRMED WORKING:
  ✅ CyberSecJobs.com RSS
  ✅ Bugcrowd careers page
  ✅ HackerOne careers page
  ✅ BuiltIn security jobs
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
    "Accept-Language": "en-US,en;q=0.9",
}

SEC_KEYWORDS = [
    "security", "cyber", "soc", "pentest", "penetration", "grc",
    "forensic", "dfir", "malware", "threat", "vulnerability",
    "appsec", "devsecops", "cloud security", "red team", "blue team",
]

def _is_sec(text: str) -> bool:
    return any(k in text.lower() for k in SEC_KEYWORDS)


# ── 1. CyberSecJobs.com RSS ──────────────────────────────────
def _fetch_cybersecjobs():
    jobs = []
    seen = set()
    feeds = [
        "https://www.cybersecjobs.com/rss/jobs",
        "https://www.cybersecjobs.com/rss/jobs?category=analyst",
        "https://www.cybersecjobs.com/rss/jobs?category=engineer",
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
                    title=title, company="CyberSecJobs",
                    location="Remote" if is_remote else "Not specified",
                    url=link, source="cybersecjobs",
                    tags=["cybersecjobs"], is_remote=is_remote,
                ))
        except ET.ParseError:
            pass
    log.info(f"CyberSecJobs: {len(jobs)} jobs")
    return jobs


# ── 2. Bugcrowd Greenhouse board ─────────────────────────────
def _fetch_bugcrowd():
    jobs = []
    url  = "https://api.greenhouse.io/v1/boards/bugcrowd/jobs?content=true"
    data = get_json(url, headers=_H)
    if not data or "jobs" not in data:
        log.info("Bugcrowd: 0 jobs")
        return jobs
    for item in data["jobs"]:
        title = item.get("title", "")
        if not _is_sec(title):
            continue
        loc      = item.get("location", {})
        location = loc.get("name", "") if isinstance(loc, dict) else ""
        is_remote = "remote" in location.lower()
        jobs.append(Job(
            title=title, company="Bugcrowd",
            location=location or "Not specified",
            url=item.get("absolute_url", ""),
            source="bugcrowd", tags=["bugcrowd"],
            is_remote=is_remote, original_source="Bugcrowd",
        ))
    log.info(f"Bugcrowd: {len(jobs)} jobs")
    return jobs


# ── 3. HackerOne careers page ────────────────────────────────
def _fetch_hackerone():
    jobs = []
    seen = set()
    url  = "https://www.hackerone.com/careers"
    html = get_text(url, headers=_H)
    if not html:
        log.info("HackerOne: 0 jobs")
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
                title = item.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                hiring  = item.get("hiringOrganization", {})
                company = hiring.get("name", "HackerOne") if isinstance(hiring, dict) else "HackerOne"
                loc_obj = item.get("jobLocation", {})
                location = ""
                if isinstance(loc_obj, dict):
                    addr = loc_obj.get("address", {})
                    if isinstance(addr, dict):
                        location = addr.get("addressLocality", "")
                is_remote = bool(item.get("jobLocationType") == "TELECOMMUTE") or "remote" in location.lower()
                jobs.append(Job(
                    title=title, company=company,
                    location=location or ("Remote" if is_remote else "Not specified"),
                    url=item.get("url", url),
                    source="hackerone", tags=["hackerone"],
                    is_remote=is_remote, original_source="HackerOne",
                ))
        except Exception:
            continue
    log.info(f"HackerOne: {len(jobs)} jobs")
    return jobs


# ── 4. BuiltIn security jobs ─────────────────────────────────
def _fetch_builtin():
    jobs = []
    seen = set()
    searches = [
        "https://builtin.com/jobs/cybersecurity",
        "https://builtin.com/jobs/information-security",
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
                    title = item.get("title", "").strip()
                    if not title or title in seen or not _is_sec(title):
                        continue
                    seen.add(title)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    loc_obj = item.get("jobLocation", {})
                    location = ""
                    if isinstance(loc_obj, dict):
                        addr = loc_obj.get("address", {})
                        if isinstance(addr, dict):
                            location = addr.get("addressLocality", addr.get("addressCountry", ""))
                    is_remote = bool(item.get("jobLocationType") == "TELECOMMUTE")
                    jobs.append(Job(
                        title=title, company=company,
                        location=location or ("Remote" if is_remote else "Not specified"),
                        url=item.get("url", url),
                        source="builtin", tags=["builtin"],
                        is_remote=is_remote,
                    ))
            except Exception:
                continue
    log.info(f"BuiltIn: {len(jobs)} jobs")
    return jobs


def fetch_cybersec_boards():
    """Fetch from confirmed-live cybersecurity job boards.
    Only Bugcrowd confirmed working — HackerOne (0 jobs), BuiltIn (0 jobs) removed.
    """
    all_jobs = []
    for fetcher in [
        _fetch_bugcrowd,
        # _fetch_hackerone,  # 0 jobs confirmed — disabled
        # _fetch_builtin,    # 0 jobs confirmed — disabled
    ]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"cybersec_boards: {fetcher.__name__} failed: {e}")
    return all_jobs
"""
Cybersecurity-specific job boards.

REMOVED (all return 404 or timeout):
  ❌ Greenhouse slugs: snyk, wiz, lacework, drata, vanta, crowdstrike,
     sentinelone, paloaltonetworks, rapid7, tenable, secureworks,
     elastic, cyberark, recordedfuture, varonis, sailpoint, axonius,
     orca, abnormalsecurity, exabeam, huntress
  ❌ Lever slugs: 1password, bitwarden, securityscorecard, cloudflare,
     intigriti, detectify, cyberark, recordedfuture, bugcrowd, synack,
     cobalt, immunefi, wazuh

CONFIRMED WORKING:
  ❌ CyberSecJobs — 404 Not Found (REMOVED)
  ✅ Bugcrowd careers page
  ✅ HackerOne careers page
  ✅ BuiltIn security jobs
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
    "Accept-Language": "en-US,en;q=0.9",
}

SEC_KEYWORDS = [
    "security", "cyber", "soc", "pentest", "penetration", "grc",
    "forensic", "dfir", "malware", "threat", "vulnerability",
    "appsec", "devsecops", "cloud security", "red team", "blue team",
]

def _is_sec(text: str) -> bool:
    return any(k in text.lower() for k in SEC_KEYWORDS)


# ── 1. Bugcrowd Greenhouse board ─────────────────────────────
def _fetch_bugcrowd():
    jobs = []
    url  = "https://api.greenhouse.io/v1/boards/bugcrowd/jobs?content=true"
    data = get_json(url, headers=_H)
    if not data or "jobs" not in data:
        log.info("Bugcrowd: 0 jobs")
        return jobs
    for item in data["jobs"]:
        title = item.get("title", "")
        if not _is_sec(title):
            continue
        loc      = item.get("location", {})
        location = loc.get("name", "") if isinstance(loc, dict) else ""
        is_remote = "remote" in location.lower()
        jobs.append(Job(
            title=title, company="Bugcrowd",
            location=location or "Not specified",
            url=item.get("absolute_url", ""),
            source="bugcrowd", tags=["bugcrowd"],
            is_remote=is_remote, original_source="Bugcrowd",
        ))
    log.info(f"Bugcrowd: {len(jobs)} jobs")
    return jobs


# ── 3. HackerOne careers page ────────────────────────────────
def _fetch_hackerone():
    jobs = []
    seen = set()
    url  = "https://www.hackerone.com/careers"
    html = get_text(url, headers=_H)
    if not html:
        log.info("HackerOne: 0 jobs")
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
                title = item.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                hiring  = item.get("hiringOrganization", {})
                company = hiring.get("name", "HackerOne") if isinstance(hiring, dict) else "HackerOne"
                loc_obj = item.get("jobLocation", {})
                location = ""
                if isinstance(loc_obj, dict):
                    addr = loc_obj.get("address", {})
                    if isinstance(addr, dict):
                        location = addr.get("addressLocality", "")
                is_remote = bool(item.get("jobLocationType") == "TELECOMMUTE") or "remote" in location.lower()
                jobs.append(Job(
                    title=title, company=company,
                    location=location or ("Remote" if is_remote else "Not specified"),
                    url=item.get("url", url),
                    source="hackerone", tags=["hackerone"],
                    is_remote=is_remote, original_source="HackerOne",
                ))
        except Exception:
            continue
    log.info(f"HackerOne: {len(jobs)} jobs")
    return jobs


# ── 4. BuiltIn security jobs ─────────────────────────────────
def _fetch_builtin():
    jobs = []
    seen = set()
    searches = [
        "https://builtin.com/jobs/cybersecurity",
        "https://builtin.com/jobs/information-security",
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
                    title = item.get("title", "").strip()
                    if not title or title in seen or not _is_sec(title):
                        continue
                    seen.add(title)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    loc_obj = item.get("jobLocation", {})
                    location = ""
                    if isinstance(loc_obj, dict):
                        addr = loc_obj.get("address", {})
                        if isinstance(addr, dict):
                            location = addr.get("addressLocality", addr.get("addressCountry", ""))
                    is_remote = bool(item.get("jobLocationType") == "TELECOMMUTE")
                    jobs.append(Job(
                        title=title, company=company,
                        location=location or ("Remote" if is_remote else "Not specified"),
                        url=item.get("url", url),
                        source="builtin", tags=["builtin"],
                        is_remote=is_remote,
                    ))
            except Exception:
                continue
    log.info(f"BuiltIn: {len(jobs)} jobs")
    return jobs


def fetch_cybersec_boards():
    """Fetch from confirmed-live cybersecurity job boards."""
    all_jobs = []
    for fetcher in [
        _fetch_bugcrowd,
        _fetch_hackerone,
        _fetch_builtin,
    ]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"cybersec_boards: {fetcher.__name__} failed: {e}")
    return all_jobs
"""
Cybersecurity-specific job boards.

REMOVED (all return 404 or timeout):
  ❌ Greenhouse slugs: snyk, wiz, lacework, drata, vanta, crowdstrike,
     sentinelone, paloaltonetworks, rapid7, tenable, secureworks,
     elastic, cyberark, recordedfuture, varonis, sailpoint, axonius,
     orca, abnormalsecurity, exabeam, huntress
  ❌ Lever slugs: 1password, bitwarden, securityscorecard, cloudflare,
     intigriti, detectify, cyberark, recordedfuture, bugcrowd, synack,
     cobalt, immunefi, wazuh

CONFIRMED WORKING:
  ✅ CyberSecJobs.com RSS
  ✅ Bugcrowd careers page
  ✅ HackerOne careers page
  ✅ BuiltIn security jobs
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
    "Accept-Language": "en-US,en;q=0.9",
}

SEC_KEYWORDS = [
    "security", "cyber", "soc", "pentest", "penetration", "grc",
    "forensic", "dfir", "malware", "threat", "vulnerability",
    "appsec", "devsecops", "cloud security", "red team", "blue team",
]

def _is_sec(text: str) -> bool:
    return any(k in text.lower() for k in SEC_KEYWORDS)


# ── 1. Bugcrowd Greenhouse board ─────────────────────────────
def _fetch_bugcrowd():
    jobs = []
    url  = "https://api.greenhouse.io/v1/boards/bugcrowd/jobs?content=true"
    data = get_json(url, headers=_H)
    if not data or "jobs" not in data:
        log.info("Bugcrowd: 0 jobs")
        return jobs
    for item in data["jobs"]:
        title = item.get("title", "")
        if not _is_sec(title):
            continue
        loc      = item.get("location", {})
        location = loc.get("name", "") if isinstance(loc, dict) else ""
        is_remote = "remote" in location.lower()
        jobs.append(Job(
            title=title, company="Bugcrowd",
            location=location or "Not specified",
            url=item.get("absolute_url", ""),
            source="bugcrowd", tags=["bugcrowd"],
            is_remote=is_remote, original_source="Bugcrowd",
        ))
    log.info(f"Bugcrowd: {len(jobs)} jobs")
    return jobs


# ── 3. HackerOne careers page ────────────────────────────────
def _fetch_hackerone():
    jobs = []
    seen = set()
    url  = "https://www.hackerone.com/careers"
    html = get_text(url, headers=_H)
    if not html:
        log.info("HackerOne: 0 jobs")
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
                title = item.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                hiring  = item.get("hiringOrganization", {})
                company = hiring.get("name", "HackerOne") if isinstance(hiring, dict) else "HackerOne"
                loc_obj = item.get("jobLocation", {})
                location = ""
                if isinstance(loc_obj, dict):
                    addr = loc_obj.get("address", {})
                    if isinstance(addr, dict):
                        location = addr.get("addressLocality", "")
                is_remote = bool(item.get("jobLocationType") == "TELECOMMUTE") or "remote" in location.lower()
                jobs.append(Job(
                    title=title, company=company,
                    location=location or ("Remote" if is_remote else "Not specified"),
                    url=item.get("url", url),
                    source="hackerone", tags=["hackerone"],
                    is_remote=is_remote, original_source="HackerOne",
                ))
        except Exception:
            continue
    log.info(f"HackerOne: {len(jobs)} jobs")
    return jobs


# ── 4. BuiltIn security jobs ─────────────────────────────────
def _fetch_builtin():
    jobs = []
    seen = set()
    searches = [
        "https://builtin.com/jobs/cybersecurity",
        "https://builtin.com/jobs/information-security",
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
                    title = item.get("title", "").strip()
                    if not title or title in seen or not _is_sec(title):
                        continue
                    seen.add(title)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    loc_obj = item.get("jobLocation", {})
                    location = ""
                    if isinstance(loc_obj, dict):
                        addr = loc_obj.get("address", {})
                        if isinstance(addr, dict):
                            location = addr.get("addressLocality", addr.get("addressCountry", ""))
                    is_remote = bool(item.get("jobLocationType") == "TELECOMMUTE")
                    jobs.append(Job(
                        title=title, company=company,
                        location=location or ("Remote" if is_remote else "Not specified"),
                        url=item.get("url", url),
                        source="builtin", tags=["builtin"],
                        is_remote=is_remote,
                    ))
            except Exception:
                continue
    log.info(f"BuiltIn: {len(jobs)} jobs")
    return jobs


def fetch_cybersec_boards():
    """Fetch from confirmed-live cybersecurity job boards."""
    all_jobs = []
    for fetcher in [
        _fetch_bugcrowd,
        _fetch_hackerone,
        _fetch_builtin,
    ]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"cybersec_boards: {fetcher.__name__} failed: {e}")
    return all_jobs
"""
Cybersecurity-specific job boards.

REMOVED (all return 404 or timeout):
  ❌ Greenhouse slugs: snyk, wiz, lacework, drata, vanta, crowdstrike,
     sentinelone, paloaltonetworks, rapid7, tenable, secureworks,
     elastic, cyberark, recordedfuture, varonis, sailpoint, axonius,
     orca, abnormalsecurity, exabeam, huntress
  ❌ Lever slugs: 1password, bitwarden, securityscorecard, cloudflare,
     intigriti, detectify, cyberark, recordedfuture, bugcrowd, synack,
     cobalt, immunefi, wazuh

CONFIRMED WORKING:
  ✅ CyberSecJobs.com RSS
  ✅ Bugcrowd careers page
  ✅ HackerOne careers page
  ✅ BuiltIn security jobs
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
    "Accept-Language": "en-US,en;q=0.9",
}

SEC_KEYWORDS = [
    "security", "cyber", "soc", "pentest", "penetration", "grc",
    "forensic", "dfir", "malware", "threat", "vulnerability",
    "appsec", "devsecops", "cloud security", "red team", "blue team",
]

def _is_sec(text: str) -> bool:
    return any(k in text.lower() for k in SEC_KEYWORDS)


# ── 1. CyberSecJobs.com RSS ──────────────────────────────────
def _fetch_cybersecjobs():
    jobs = []
    seen = set()
    feeds = [
        "https://www.cybersecjobs.com/rss/jobs",
        "https://www.cybersecjobs.com/rss/jobs?category=analyst",
        "https://www.cybersecjobs.com/rss/jobs?category=engineer",
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
                    title=title, company="CyberSecJobs",
                    location="Remote" if is_remote else "Not specified",
                    url=link, source="cybersecjobs",
                    tags=["cybersecjobs"], is_remote=is_remote,
                ))
        except ET.ParseError:
            pass
    log.info(f"CyberSecJobs: {len(jobs)} jobs")
    return jobs


# ── 2. Bugcrowd Greenhouse board ─────────────────────────────
def _fetch_bugcrowd():
    jobs = []
    url  = "https://api.greenhouse.io/v1/boards/bugcrowd/jobs?content=true"
    data = get_json(url, headers=_H)
    if not data or "jobs" not in data:
        log.info("Bugcrowd: 0 jobs")
        return jobs
    for item in data["jobs"]:
        title = item.get("title", "")
        if not _is_sec(title):
            continue
        loc      = item.get("location", {})
        location = loc.get("name", "") if isinstance(loc, dict) else ""
        is_remote = "remote" in location.lower()
        jobs.append(Job(
            title=title, company="Bugcrowd",
            location=location or "Not specified",
            url=item.get("absolute_url", ""),
            source="bugcrowd", tags=["bugcrowd"],
            is_remote=is_remote, original_source="Bugcrowd",
        ))
    log.info(f"Bugcrowd: {len(jobs)} jobs")
    return jobs


# ── 3. HackerOne careers page ────────────────────────────────
def _fetch_hackerone():
    jobs = []
    seen = set()
    url  = "https://www.hackerone.com/careers"
    html = get_text(url, headers=_H)
    if not html:
        log.info("HackerOne: 0 jobs")
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
                title = item.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                hiring  = item.get("hiringOrganization", {})
                company = hiring.get("name", "HackerOne") if isinstance(hiring, dict) else "HackerOne"
                loc_obj = item.get("jobLocation", {})
                location = ""
                if isinstance(loc_obj, dict):
                    addr = loc_obj.get("address", {})
                    if isinstance(addr, dict):
                        location = addr.get("addressLocality", "")
                is_remote = bool(item.get("jobLocationType") == "TELECOMMUTE") or "remote" in location.lower()
                jobs.append(Job(
                    title=title, company=company,
                    location=location or ("Remote" if is_remote else "Not specified"),
                    url=item.get("url", url),
                    source="hackerone", tags=["hackerone"],
                    is_remote=is_remote, original_source="HackerOne",
                ))
        except Exception:
            continue
    log.info(f"HackerOne: {len(jobs)} jobs")
    return jobs


# ── 4. BuiltIn security jobs ─────────────────────────────────
def _fetch_builtin():
    jobs = []
    seen = set()
    searches = [
        "https://builtin.com/jobs/cybersecurity",
        "https://builtin.com/jobs/information-security",
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
                    title = item.get("title", "").strip()
                    if not title or title in seen or not _is_sec(title):
                        continue
                    seen.add(title)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    loc_obj = item.get("jobLocation", {})
                    location = ""
                    if isinstance(loc_obj, dict):
                        addr = loc_obj.get("address", {})
                        if isinstance(addr, dict):
                            location = addr.get("addressLocality", addr.get("addressCountry", ""))
                    is_remote = bool(item.get("jobLocationType") == "TELECOMMUTE")
                    jobs.append(Job(
                        title=title, company=company,
                        location=location or ("Remote" if is_remote else "Not specified"),
                        url=item.get("url", url),
                        source="builtin", tags=["builtin"],
                        is_remote=is_remote,
                    ))
            except Exception:
                continue
    log.info(f"BuiltIn: {len(jobs)} jobs")
    return jobs


def fetch_cybersec_boards():
    """Fetch from confirmed-live cybersecurity job boards."""
    all_jobs = []
    for fetcher in [
        # _fetch_cybersecjobs,  # 404 confirmed dead — disabled V21
        _fetch_bugcrowd,
        _fetch_hackerone,
        _fetch_builtin,
    ]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"cybersec_boards: {fetcher.__name__} failed: {e}")
    return all_jobs
"""
Cybersecurity-specific job boards.

REMOVED (all return 404 or timeout):
  ❌ Greenhouse slugs: snyk, wiz, lacework, drata, vanta, crowdstrike,
     sentinelone, paloaltonetworks, rapid7, tenable, secureworks,
     elastic, cyberark, recordedfuture, varonis, sailpoint, axonius,
     orca, abnormalsecurity, exabeam, huntress
  ❌ Lever slugs: 1password, bitwarden, securityscorecard, cloudflare,
     intigriti, detectify, cyberark, recordedfuture, bugcrowd, synack,
     cobalt, immunefi, wazuh

CONFIRMED WORKING:
  ❌ CyberSecJobs — 404 Not Found (REMOVED)
  ✅ Bugcrowd careers page
  ✅ HackerOne careers page
  ✅ BuiltIn security jobs
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
    "Accept-Language": "en-US,en;q=0.9",
}

SEC_KEYWORDS = [
    "security", "cyber", "soc", "pentest", "penetration", "grc",
    "forensic", "dfir", "malware", "threat", "vulnerability",
    "appsec", "devsecops", "cloud security", "red team", "blue team",
]

def _is_sec(text: str) -> bool:
    return any(k in text.lower() for k in SEC_KEYWORDS)


# ── 1. Bugcrowd Greenhouse board ─────────────────────────────
def _fetch_bugcrowd():
    jobs = []
    url  = "https://api.greenhouse.io/v1/boards/bugcrowd/jobs?content=true"
    data = get_json(url, headers=_H)
    if not data or "jobs" not in data:
        log.info("Bugcrowd: 0 jobs")
        return jobs
    for item in data["jobs"]:
        title = item.get("title", "")
        if not _is_sec(title):
            continue
        loc      = item.get("location", {})
        location = loc.get("name", "") if isinstance(loc, dict) else ""
        is_remote = "remote" in location.lower()
        jobs.append(Job(
            title=title, company="Bugcrowd",
            location=location or "Not specified",
            url=item.get("absolute_url", ""),
            source="bugcrowd", tags=["bugcrowd"],
            is_remote=is_remote, original_source="Bugcrowd",
        ))
    log.info(f"Bugcrowd: {len(jobs)} jobs")
    return jobs


# ── 3. HackerOne careers page ────────────────────────────────
def _fetch_hackerone():
    jobs = []
    seen = set()
    url  = "https://www.hackerone.com/careers"
    html = get_text(url, headers=_H)
    if not html:
        log.info("HackerOne: 0 jobs")
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
                title = item.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                hiring  = item.get("hiringOrganization", {})
                company = hiring.get("name", "HackerOne") if isinstance(hiring, dict) else "HackerOne"
                loc_obj = item.get("jobLocation", {})
                location = ""
                if isinstance(loc_obj, dict):
                    addr = loc_obj.get("address", {})
                    if isinstance(addr, dict):
                        location = addr.get("addressLocality", "")
                is_remote = bool(item.get("jobLocationType") == "TELECOMMUTE") or "remote" in location.lower()
                jobs.append(Job(
                    title=title, company=company,
                    location=location or ("Remote" if is_remote else "Not specified"),
                    url=item.get("url", url),
                    source="hackerone", tags=["hackerone"],
                    is_remote=is_remote, original_source="HackerOne",
                ))
        except Exception:
            continue
    log.info(f"HackerOne: {len(jobs)} jobs")
    return jobs


# ── 4. BuiltIn security jobs ─────────────────────────────────
def _fetch_builtin():
    jobs = []
    seen = set()
    searches = [
        "https://builtin.com/jobs/cybersecurity",
        "https://builtin.com/jobs/information-security",
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
                    title = item.get("title", "").strip()
                    if not title or title in seen or not _is_sec(title):
                        continue
                    seen.add(title)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    loc_obj = item.get("jobLocation", {})
                    location = ""
                    if isinstance(loc_obj, dict):
                        addr = loc_obj.get("address", {})
                        if isinstance(addr, dict):
                            location = addr.get("addressLocality", addr.get("addressCountry", ""))
                    is_remote = bool(item.get("jobLocationType") == "TELECOMMUTE")
                    jobs.append(Job(
                        title=title, company=company,
                        location=location or ("Remote" if is_remote else "Not specified"),
                        url=item.get("url", url),
                        source="builtin", tags=["builtin"],
                        is_remote=is_remote,
                    ))
            except Exception:
                continue
    log.info(f"BuiltIn: {len(jobs)} jobs")
    return jobs


def fetch_cybersec_boards():
    """Fetch from confirmed-live cybersecurity job boards."""
    all_jobs = []
    for fetcher in [
        _fetch_bugcrowd,
        _fetch_hackerone,
        _fetch_builtin,
    ]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"cybersec_boards: {fetcher.__name__} failed: {e}")
    return all_jobs
"""
Cybersecurity-specific job boards.

REMOVED (all return 404 or timeout):
  ❌ Greenhouse slugs: snyk, wiz, lacework, drata, vanta, crowdstrike,
     sentinelone, paloaltonetworks, rapid7, tenable, secureworks,
     elastic, cyberark, recordedfuture, varonis, sailpoint, axonius,
     orca, abnormalsecurity, exabeam, huntress
  ❌ Lever slugs: 1password, bitwarden, securityscorecard, cloudflare,
     intigriti, detectify, cyberark, recordedfuture, bugcrowd, synack,
     cobalt, immunefi, wazuh

CONFIRMED WORKING:
  ✅ CyberSecJobs.com RSS
  ✅ Bugcrowd careers page
  ✅ HackerOne careers page
  ✅ BuiltIn security jobs
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
    "Accept-Language": "en-US,en;q=0.9",
}

SEC_KEYWORDS = [
    "security", "cyber", "soc", "pentest", "penetration", "grc",
    "forensic", "dfir", "malware", "threat", "vulnerability",
    "appsec", "devsecops", "cloud security", "red team", "blue team",
]

def _is_sec(text: str) -> bool:
    return any(k in text.lower() for k in SEC_KEYWORDS)


# ── 1. Bugcrowd Greenhouse board ─────────────────────────────
def _fetch_bugcrowd():
    jobs = []
    url  = "https://api.greenhouse.io/v1/boards/bugcrowd/jobs?content=true"
    data = get_json(url, headers=_H)
    if not data or "jobs" not in data:
        log.info("Bugcrowd: 0 jobs")
        return jobs
    for item in data["jobs"]:
        title = item.get("title", "")
        if not _is_sec(title):
            continue
        loc      = item.get("location", {})
        location = loc.get("name", "") if isinstance(loc, dict) else ""
        is_remote = "remote" in location.lower()
        jobs.append(Job(
            title=title, company="Bugcrowd",
            location=location or "Not specified",
            url=item.get("absolute_url", ""),
            source="bugcrowd", tags=["bugcrowd"],
            is_remote=is_remote, original_source="Bugcrowd",
        ))
    log.info(f"Bugcrowd: {len(jobs)} jobs")
    return jobs


# ── 3. HackerOne careers page ────────────────────────────────
def _fetch_hackerone():
    jobs = []
    seen = set()
    url  = "https://www.hackerone.com/careers"
    html = get_text(url, headers=_H)
    if not html:
        log.info("HackerOne: 0 jobs")
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
                title = item.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                hiring  = item.get("hiringOrganization", {})
                company = hiring.get("name", "HackerOne") if isinstance(hiring, dict) else "HackerOne"
                loc_obj = item.get("jobLocation", {})
                location = ""
                if isinstance(loc_obj, dict):
                    addr = loc_obj.get("address", {})
                    if isinstance(addr, dict):
                        location = addr.get("addressLocality", "")
                is_remote = bool(item.get("jobLocationType") == "TELECOMMUTE") or "remote" in location.lower()
                jobs.append(Job(
                    title=title, company=company,
                    location=location or ("Remote" if is_remote else "Not specified"),
                    url=item.get("url", url),
                    source="hackerone", tags=["hackerone"],
                    is_remote=is_remote, original_source="HackerOne",
                ))
        except Exception:
            continue
    log.info(f"HackerOne: {len(jobs)} jobs")
    return jobs


# ── 4. BuiltIn security jobs ─────────────────────────────────
def _fetch_builtin():
    jobs = []
    seen = set()
    searches = [
        "https://builtin.com/jobs/cybersecurity",
        "https://builtin.com/jobs/information-security",
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
                    title = item.get("title", "").strip()
                    if not title or title in seen or not _is_sec(title):
                        continue
                    seen.add(title)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    loc_obj = item.get("jobLocation", {})
                    location = ""
                    if isinstance(loc_obj, dict):
                        addr = loc_obj.get("address", {})
                        if isinstance(addr, dict):
                            location = addr.get("addressLocality", addr.get("addressCountry", ""))
                    is_remote = bool(item.get("jobLocationType") == "TELECOMMUTE")
                    jobs.append(Job(
                        title=title, company=company,
                        location=location or ("Remote" if is_remote else "Not specified"),
                        url=item.get("url", url),
                        source="builtin", tags=["builtin"],
                        is_remote=is_remote,
                    ))
            except Exception:
                continue
    log.info(f"BuiltIn: {len(jobs)} jobs")
    return jobs


def fetch_cybersec_boards():
    """Fetch from confirmed-live cybersecurity job boards."""
    all_jobs = []
    for fetcher in [
        _fetch_bugcrowd,
        _fetch_hackerone,
        _fetch_builtin,
    ]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"cybersec_boards: {fetcher.__name__} failed: {e}")
    return all_jobs
"""
Cybersecurity-specific job boards.

REMOVED (all return 404 or timeout):
  ❌ Greenhouse slugs: snyk, wiz, lacework, drata, vanta, crowdstrike,
     sentinelone, paloaltonetworks, rapid7, tenable, secureworks,
     elastic, cyberark, recordedfuture, varonis, sailpoint, axonius,
     orca, abnormalsecurity, exabeam, huntress
  ❌ Lever slugs: 1password, bitwarden, securityscorecard, cloudflare,
     intigriti, detectify, cyberark, recordedfuture, bugcrowd, synack,
     cobalt, immunefi, wazuh

CONFIRMED WORKING:
  ✅ CyberSecJobs.com RSS
  ✅ Bugcrowd careers page
  ✅ HackerOne careers page
  ✅ BuiltIn security jobs
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
    "Accept-Language": "en-US,en;q=0.9",
}

SEC_KEYWORDS = [
    "security", "cyber", "soc", "pentest", "penetration", "grc",
    "forensic", "dfir", "malware", "threat", "vulnerability",
    "appsec", "devsecops", "cloud security", "red team", "blue team",
]

def _is_sec(text: str) -> bool:
    return any(k in text.lower() for k in SEC_KEYWORDS)


# ── 1. CyberSecJobs.com RSS ──────────────────────────────────
def _fetch_cybersecjobs():
    jobs = []
    seen = set()
    feeds = [
        "https://www.cybersecjobs.com/rss/jobs",
        "https://www.cybersecjobs.com/rss/jobs?category=analyst",
        "https://www.cybersecjobs.com/rss/jobs?category=engineer",
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
                    title=title, company="CyberSecJobs",
                    location="Remote" if is_remote else "Not specified",
                    url=link, source="cybersecjobs",
                    tags=["cybersecjobs"], is_remote=is_remote,
                ))
        except ET.ParseError:
            pass
    log.info(f"CyberSecJobs: {len(jobs)} jobs")
    return jobs


# ── 2. Bugcrowd Greenhouse board ─────────────────────────────
def _fetch_bugcrowd():
    jobs = []
    url  = "https://api.greenhouse.io/v1/boards/bugcrowd/jobs?content=true"
    data = get_json(url, headers=_H)
    if not data or "jobs" not in data:
        log.info("Bugcrowd: 0 jobs")
        return jobs
    for item in data["jobs"]:
        title = item.get("title", "")
        if not _is_sec(title):
            continue
        loc      = item.get("location", {})
        location = loc.get("name", "") if isinstance(loc, dict) else ""
        is_remote = "remote" in location.lower()
        jobs.append(Job(
            title=title, company="Bugcrowd",
            location=location or "Not specified",
            url=item.get("absolute_url", ""),
            source="bugcrowd", tags=["bugcrowd"],
            is_remote=is_remote, original_source="Bugcrowd",
        ))
    log.info(f"Bugcrowd: {len(jobs)} jobs")
    return jobs


# ── 3. HackerOne careers page ────────────────────────────────
def _fetch_hackerone():
    jobs = []
    seen = set()
    url  = "https://www.hackerone.com/careers"
    html = get_text(url, headers=_H)
    if not html:
        log.info("HackerOne: 0 jobs")
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
                title = item.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                hiring  = item.get("hiringOrganization", {})
                company = hiring.get("name", "HackerOne") if isinstance(hiring, dict) else "HackerOne"
                loc_obj = item.get("jobLocation", {})
                location = ""
                if isinstance(loc_obj, dict):
                    addr = loc_obj.get("address", {})
                    if isinstance(addr, dict):
                        location = addr.get("addressLocality", "")
                is_remote = bool(item.get("jobLocationType") == "TELECOMMUTE") or "remote" in location.lower()
                jobs.append(Job(
                    title=title, company=company,
                    location=location or ("Remote" if is_remote else "Not specified"),
                    url=item.get("url", url),
                    source="hackerone", tags=["hackerone"],
                    is_remote=is_remote, original_source="HackerOne",
                ))
        except Exception:
            continue
    log.info(f"HackerOne: {len(jobs)} jobs")
    return jobs


# ── 4. BuiltIn security jobs ─────────────────────────────────
def _fetch_builtin():
    jobs = []
    seen = set()
    searches = [
        "https://builtin.com/jobs/cybersecurity",
        "https://builtin.com/jobs/information-security",
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
                    title = item.get("title", "").strip()
                    if not title or title in seen or not _is_sec(title):
                        continue
                    seen.add(title)
                    hiring  = item.get("hiringOrganization", {})
                    company = hiring.get("name", "") if isinstance(hiring, dict) else ""
                    loc_obj = item.get("jobLocation", {})
                    location = ""
                    if isinstance(loc_obj, dict):
                        addr = loc_obj.get("address", {})
                        if isinstance(addr, dict):
                            location = addr.get("addressLocality", addr.get("addressCountry", ""))
                    is_remote = bool(item.get("jobLocationType") == "TELECOMMUTE")
                    jobs.append(Job(
                        title=title, company=company,
                        location=location or ("Remote" if is_remote else "Not specified"),
                        url=item.get("url", url),
                        source="builtin", tags=["builtin"],
                        is_remote=is_remote,
                    ))
            except Exception:
                continue
    log.info(f"BuiltIn: {len(jobs)} jobs")
    return jobs


def fetch_cybersec_boards():
    """Fetch from confirmed-live cybersecurity job boards."""
    all_jobs = []
    for fetcher in [
        _fetch_cybersecjobs,
        _fetch_bugcrowd,
        _fetch_hackerone,
        _fetch_builtin,
    ]:
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"cybersec_boards: {fetcher.__name__} failed: {e}")
    return all_jobs
