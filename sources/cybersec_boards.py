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




# ── Wuzzuf (Egypt #1) ─────────────────────────────────────────
WUZZUF_QUERIES = [
    "cybersecurity", "information security", "SOC analyst",
    "penetration testing", "security engineer", "network security",
    "security analyst", "cloud security", "GRC", "security intern",
    "junior security", "malware analyst", "threat intelligence",
]

def _fetch_wuzzuf() -> list[Job]:
    jobs = []
    seen = set()
    for q in WUZZUF_QUERIES:
        rss_url = "https://wuzzuf.net/rss/jobs?q=" + q.replace(" ", "+") + "&country=EG"
        xml = get_text(rss_url, headers=_HEADERS)
        if not xml:
            continue
        try:
            root = ET.fromstring(xml)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link", "").strip()
                desc  = item.findtext("description", "") or ""
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                company = item.findtext("author", "").strip() or "Unknown"
                location = "Egypt"
                m = re.search(r"(?:Location|City)[:\s]+([^\n<|,]+)", desc, re.IGNORECASE)
                if m:
                    location = m.group(1).strip() + ", Egypt"
                jobs.append(Job(
                    title=title, company=company, location=location,
                    url=link, source="wuzzuf", tags=["wuzzuf", q], is_remote=False,
                ))
        except ET.ParseError as e:
            log.warning("Wuzzuf RSS parse error: " + str(e))
    log.info("Wuzzuf: " + str(len(jobs)) + " jobs")
    return jobs


# ── Forasna (Egypt #2) ────────────────────────────────────────
FORASNA_QUERIES = [
    "cybersecurity", "information+security", "SOC+analyst",
    "security+engineer", "network+security", "security+analyst",
]

def _fetch_forasna() -> list[Job]:
    jobs = []
    seen = set()
    for q in FORASNA_QUERIES:
        rss_url = "https://www.forasna.com/jobs/rss?q=" + q + "&country=EG"
        xml = get_text(rss_url, headers=_HEADERS)
        if not xml:
            continue
        try:
            root = ET.fromstring(xml)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link", "").strip()
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                jobs.append(Job(
                    title=title,
                    company=item.findtext("author", "").strip() or "Unknown",
                    location="Egypt",
                    url=link, source="forasna", tags=["forasna"], is_remote=False,
                ))
        except ET.ParseError as e:
            log.warning("Forasna RSS parse error: " + str(e))
    log.info("Forasna: " + str(len(jobs)) + " jobs")
    return jobs


# ── Bayt (Gulf #1) ────────────────────────────────────────────
BAYT_SEARCHES = [
    ("cybersecurity",        "saudi-arabia",        "Saudi Arabia"),
    ("soc-analyst",          "saudi-arabia",        "Saudi Arabia"),
    ("security-engineer",    "saudi-arabia",        "Saudi Arabia"),
    ("penetration-tester",   "saudi-arabia",        "Saudi Arabia"),
    ("information-security", "saudi-arabia",        "Saudi Arabia"),
    ("cybersecurity",        "united-arab-emirates","UAE"),
    ("soc-analyst",          "united-arab-emirates","UAE"),
    ("security-engineer",    "united-arab-emirates","UAE"),
    ("cybersecurity",        "qatar",               "Qatar"),
    ("security-engineer",    "qatar",               "Qatar"),
    ("cybersecurity",        "kuwait",              "Kuwait"),
    ("cybersecurity",        "bahrain",             "Bahrain"),
    ("cybersecurity",        "oman",                "Oman"),
    ("cybersecurity",        "egypt",               "Egypt"),
    ("soc-analyst",          "egypt",               "Egypt"),
    ("security-engineer",    "egypt",               "Egypt"),
]

def _fetch_bayt() -> list[Job]:
    jobs = []
    seen = set()
    for keyword, country, location_label in BAYT_SEARCHES:
        rss_url = (
            "https://www.bayt.com/en/" + country + "/jobs/"
            + keyword + "-jobs/?rss=1"
        )
        xml = get_text(rss_url, headers=_HEADERS)
        if not xml:
            continue
        try:
            root = ET.fromstring(xml)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link", "").strip()
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                desc = item.findtext("description", "") or ""
                company = item.findtext("author", "").strip() or "Unknown"
                m = re.search(r"(?:Company|Employer)[:\s]+([^\n<|]+)", desc, re.IGNORECASE)
                if m:
                    company = m.group(1).strip()
                jobs.append(Job(
                    title=title, company=company, location=location_label,
                    url=link, source="bayt", tags=["bayt", keyword], is_remote=False,
                ))
        except ET.ParseError as e:
            log.warning("Bayt RSS parse error: " + str(e))
    log.info("Bayt: " + str(len(jobs)) + " jobs")
    return jobs


# ── Naukrigulf (Gulf #2) ──────────────────────────────────────
NAUKRIGULF_SEARCHES = [
    ("cybersecurity",        "saudi-arabia", "Saudi Arabia"),
    ("information-security", "saudi-arabia", "Saudi Arabia"),
    ("soc-analyst",          "saudi-arabia", "Saudi Arabia"),
    ("security-engineer",    "saudi-arabia", "Saudi Arabia"),
    ("cybersecurity",        "uae",          "UAE"),
    ("soc-analyst",          "uae",          "UAE"),
    ("security-engineer",    "uae",          "UAE"),
    ("cybersecurity",        "qatar",        "Qatar"),
    ("cybersecurity",        "kuwait",       "Kuwait"),
    ("cybersecurity",        "bahrain",      "Bahrain"),
    ("cybersecurity",        "oman",         "Oman"),
]

def _fetch_naukrigulf() -> list[Job]:
    jobs = []
    seen = set()
    for keyword, country, location_label in NAUKRIGULF_SEARCHES:
        rss_url = (
            "https://www.naukrigulf.com/rss/"
            + keyword + "-jobs-in-" + country
        )
        xml = get_text(rss_url, headers=_HEADERS)
        if not xml:
            continue
        try:
            root = ET.fromstring(xml)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link", "").strip()
                if not title or not link or link in seen:
                    continue
                seen.add(link)
                jobs.append(Job(
                    title=title,
                    company=item.findtext("author", "").strip() or "Unknown",
                    location=location_label,
                    url=link, source="naukrigulf", tags=["naukrigulf"], is_remote=False,
                ))
        except ET.ParseError as e:
            log.warning("Naukrigulf RSS parse error: " + str(e))
    log.info("Naukrigulf: " + str(len(jobs)) + " jobs")
    return jobs


def fetch_cybersec_boards() -> list[Job]:
    """Aggregate all cybersecurity-specific board results."""
    all_jobs = []
    for fn in [
        _fetch_wuzzuf,
        _fetch_bayt,
        _fetch_naukrigulf,
        _fetch_forasna,
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
            log.warning("CyberSecBoard sub-fetcher " + fn.__name__ + " failed: " + str(e))
    return all_jobs
