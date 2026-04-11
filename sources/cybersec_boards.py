"""
Cybersecurity-specific job boards (RSS feeds — no API key needed):
  - InfoSec-Jobs.com
  - CyberSecJobs.com
  - SecurityJobs.net
  - ISACA Job Board
  - (ISC)² Career Center
  - ClearanceJobs (cleared security roles — mostly US, filtered by geo later)
"""

import logging
import xml.etree.ElementTree as ET
import re
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 CyberSecJobsBot/2.0"}


def _parse_rss(url: str, source_name: str, source_key: str) -> list[Job]:
    """Generic RSS parser — handles standard job board RSS feeds."""
    xml = get_text(url, headers=_HEADERS)
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

            # Try extracting location from description
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

            jobs.append(Job(
                title=title,
                company=item.findtext("author", source_name).strip() or source_name,
                location=location or ("Remote" if is_remote else "Not specified"),
                url=link,
                source=source_key,
                salary="",
                job_type="",
                tags=[source_name],
                is_remote=is_remote,
            ))
    except ET.ParseError as e:
        log.warning(f"{source_name} RSS parse error: {e}")
    return jobs


# ── InfoSec-Jobs.com ──────────────────────────────────────────
def _fetch_infosec_jobs() -> list[Job]:
    jobs = []
    for url in [
        "https://infosec-jobs.com/feeds/remote/",
        "https://infosec-jobs.com/feeds/all/",
    ]:
        jobs.extend(_parse_rss(url, "InfoSec-Jobs", "infosec_jobs"))
    log.info(f"InfoSec-Jobs: {len(jobs)} jobs")
    return jobs


# ── CyberSecJobs.com ─────────────────────────────────────────
def _fetch_cybersecjobs() -> list[Job]:
    jobs = []
    for url in [
        "https://cybersecjobs.com/feed/",
        "https://cybersecjobs.com/category/remote/feed/",
    ]:
        jobs.extend(_parse_rss(url, "CyberSecJobs", "cybersecjobs"))
    log.info(f"CyberSecJobs: {len(jobs)} jobs")
    return jobs


# ── SecurityJobs.net ─────────────────────────────────────────
def _fetch_securityjobs() -> list[Job]:
    jobs = []
    for url in [
        "https://www.securityjobs.net/rss/cybersecurity-jobs.xml",
        "https://www.securityjobs.net/rss/remote-security-jobs.xml",
    ]:
        jobs.extend(_parse_rss(url, "SecurityJobs", "securityjobs"))
    log.info(f"SecurityJobs: {len(jobs)} jobs")
    return jobs


# ── ISACA Job Board ───────────────────────────────────────────
def _fetch_isaca() -> list[Job]:
    jobs = []
    for url in [
        "https://jobs.isaca.org/jobs.rss?keywords=cybersecurity",
        "https://jobs.isaca.org/jobs.rss?keywords=GRC",
        "https://jobs.isaca.org/jobs.rss?keywords=information+security",
    ]:
        jobs.extend(_parse_rss(url, "ISACA", "isaca"))
    log.info(f"ISACA: {len(jobs)} jobs")
    return jobs


# ── (ISC)² Career Center ─────────────────────────────────────
def _fetch_isc2() -> list[Job]:
    jobs = []
    for url in [
        "https://isc2.org/Careers/jobboard/jobs.rss",
    ]:
        jobs.extend(_parse_rss(url, "(ISC)²", "isc2"))
    log.info(f"(ISC)²: {len(jobs)} jobs")
    return jobs


# ── ClearanceJobs (US cleared roles — geo filter will handle) ─
def _fetch_clearancejobs() -> list[Job]:
    jobs = []
    for url in [
        "https://www.clearancejobs.com/jobs.rss?keywords=cybersecurity",
        "https://www.clearancejobs.com/jobs.rss?keywords=information+security",
    ]:
        jobs.extend(_parse_rss(url, "ClearanceJobs", "clearancejobs"))
    log.info(f"ClearanceJobs: {len(jobs)} jobs")
    return jobs


def fetch_cybersec_boards() -> list[Job]:
    """Aggregate all cybersecurity-specific board results."""
    all_jobs = []
    for fn in [
        _fetch_infosec_jobs,
        _fetch_cybersecjobs,
        _fetch_securityjobs,
        _fetch_isaca,
        _fetch_isc2,
        _fetch_clearancejobs,
    ]:
        try:
            all_jobs.extend(fn())
        except Exception as e:
            log.warning(f"CyberSecBoard sub-fetcher {fn.__name__} failed: {e}")
    return all_jobs
