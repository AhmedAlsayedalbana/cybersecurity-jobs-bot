"""
Freelance platforms — cybersecurity gigs only.
Sources: Upwork RSS, Freelancer.com RSS, Khamsat (خمسات), Mustaqil (مستقل).
All are public RSS/JSON feeds — no API keys needed.
"""

import logging
import xml.etree.ElementTree as ET
import re
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 CyberSecJobsBot/2.0"}


# ── Upwork ────────────────────────────────────────────────────
# Upwork removed public RSS (410 Gone in 2024).
# Use their public job search JSON endpoint instead.
UPWORK_QUERIES = [
    "cybersecurity", "penetration testing", "security audit",
    "ethical hacking", "network security", "devsecops",
]


def _fetch_upwork() -> list[Job]:
    """
    Upwork's old RSS is dead (410). Their search page embeds job data as JSON.
    We fetch the search page and extract JSON-LD or embedded __NEXT_DATA__.
    """
    import json
    jobs = []
    seen = set()

    for q in UPWORK_QUERIES:
        q_enc = q.replace(" ", "%20")
        # Upwork search URL
        url = f"https://www.upwork.com/nx/jobs/search/?q={q_enc}&sort=recency"
        html = get_text(url, headers={
            **_HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        if not html:
            continue

        # Try to extract __NEXT_DATA__ JSON (Next.js apps embed data this way)
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                job_list = (
                    data.get("props", {})
                        .get("pageProps", {})
                        .get("serverProps", {})
                        .get("jobs", [])
                ) or []
                for item in job_list[:10]:
                    title = item.get("title", "").strip()
                    ciphertext = item.get("ciphertext", "")
                    link = f"https://www.upwork.com/jobs/~{ciphertext}" if ciphertext else url
                    if not title or link in seen:
                        continue
                    seen.add(link)
                    jobs.append(Job(
                        title=title,
                        company="Upwork Client",
                        location="Remote",
                        url=link,
                        source="upwork",
                        job_type="Freelance",
                        tags=[q, "freelance"],
                        is_remote=True,
                    ))
            except (json.JSONDecodeError, KeyError):
                pass

        # Fallback: JSON-LD
        if not jobs:
            for block in re.findall(
                r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                html, re.DOTALL | re.IGNORECASE
            ):
                try:
                    data = json.loads(block.strip())
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if item.get("@type") != "JobPosting":
                            continue
                        title = item.get("title", "").strip()
                        link = item.get("url", url)
                        if not title or link in seen:
                            continue
                        seen.add(link)
                        jobs.append(Job(
                            title=title, company="Upwork Client", location="Remote",
                            url=link, source="upwork", job_type="Freelance",
                            tags=[q, "freelance"], is_remote=True,
                        ))
                except (json.JSONDecodeError, KeyError):
                    continue

    log.info(f"Upwork: {len(jobs)} jobs")
    return jobs


# ── Freelancer.com RSS ────────────────────────────────────────
# RSS path changed from /rss/category/projects/{q} to /rss/projects/{skill_id}
# Using their keyword search RSS instead
FREELANCER_QUERIES = [
    ("cybersecurity",      "459"),   # skill ID for cybersecurity
    ("penetration-testing","160"),   # ethical hacking skill ID
    ("network-security",   "55"),    # networking
    ("information-security","459"),
]


def _fetch_freelancer() -> list[Job]:
    jobs = []
    seen = set()
    for q, skill_id in FREELANCER_QUERIES:
        # Try both the new RSS path and the search RSS
        urls_to_try = [
            f"https://www.freelancer.com/rss/projects/{skill_id}.xml",
            f"https://www.freelancer.com/jobs/{q}/",
        ]
        for url in urls_to_try:
            xml = get_text(url, headers=_HEADERS)
            if not xml or not xml.strip().startswith("<"):
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
                        title=title,
                        company="Freelancer Client",
                        location="Remote",
                        url=link,
                        source="freelancer",
                        job_type="Freelance",
                        tags=[q, "freelance"],
                        is_remote=True,
                    ))
                break  # stop trying URLs if one worked
            except ET.ParseError:
                pass
    log.info(f"Freelancer.com: {len(jobs)} jobs")
    return jobs


# ── Khamsat (خمسات) ───────────────────────────────────────────
KHAMSAT_URLS = [
    "https://khamsat.com/technology/cybersecurity?format=rss",
    "https://khamsat.com/technology/networking?format=rss",
]


def _fetch_khamsat() -> list[Job]:
    jobs = []
    for url in KHAMSAT_URLS:
        xml = get_text(url, headers=_HEADERS)
        if not xml:
            continue
        try:
            root = ET.fromstring(xml)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                if not title or not link:
                    continue
                jobs.append(Job(
                    title=title,
                    company="خمسات",
                    location="Remote",
                    url=link,
                    source="khamsat",
                    job_type="Freelance",
                    tags=["خمسات", "cybersecurity", "freelance"],
                    is_remote=True,
                ))
        except ET.ParseError:
            pass
    log.info(f"Khamsat: {len(jobs)} jobs")
    return jobs


# ── Mustaqil / Mostaql (مستقل) ───────────────────────────────
MUSTAQIL_URLS = [
    "https://mostaql.com/projects?category=network-information-security&budget_max=&sort=date",
    "https://mostaql.com/projects?category=network-information-security&budget_max=&sort=date",
    "https://mostaql.com/projects?category=network-information-security&keywords=penetration&sort=date",
    "https://mostaql.com/projects?category=network-information-security&keywords=%D8%A3%D9%85%D9%86&sort=date",
]


def _fetch_mustaqil() -> list[Job]:
    jobs = []
    for url in MUSTAQIL_URLS:
        xml = get_text(url, headers=_HEADERS)
        if not xml:
            continue
        try:
            root = ET.fromstring(xml)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                if not title or not link:
                    continue
                jobs.append(Job(
                    title=title,
                    company="مستقل",
                    location="Remote",
                    url=link,
                    source="mustaqil",
                    job_type="Freelance",
                    tags=["مستقل", "cybersecurity", "freelance"],
                    is_remote=True,
                ))
        except ET.ParseError:
            pass
    log.info(f"Mustaqil: {len(jobs)} jobs")
    return jobs


def fetch_freelance() -> list[Job]:
    """Aggregate all freelance platforms."""
    jobs = []
    for fetcher in [_fetch_upwork, _fetch_freelancer, _fetch_khamsat, _fetch_mustaqil]:
        try:
            jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"Freelance sub-fetcher {fetcher.__name__} failed: {e}")
    return jobs
"""
Freelance platforms — cybersecurity gigs only.
Sources: Upwork RSS, Freelancer.com RSS, Khamsat (خمسات), Mustaqil (مستقل).
All are public RSS/JSON feeds — no API keys needed.
"""

import logging
import xml.etree.ElementTree as ET
import re
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 CyberSecJobsBot/2.0"}


# ── Upwork RSS ────────────────────────────────────────────────
UPWORK_QUERIES = [
    "cybersecurity", "penetration testing", "security audit",
    "ethical hacking", "network security", "malware analysis",
    "application security", "devsecops", "vulnerability assessment",
]


def _fetch_upwork() -> list[Job]:
    jobs = []
    for q in UPWORK_QUERIES:
        url = f"https://www.upwork.com/ab/feed/jobs/rss?q={q.replace(' ', '+')}&sort=recency"
        xml = get_text(url, headers=_HEADERS)
        if not xml:
            continue
        try:
            root = ET.fromstring(xml)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                desc  = item.findtext("description", "") or ""
                if not title or not link:
                    continue
                budget = ""
                m = re.search(r"\$[\d,]+(?:\s*[-–]\s*\$[\d,]+)?", desc)
                if m:
                    budget = m.group(0)
                jobs.append(Job(
                    title=title,
                    company="Upwork Client",
                    location="Remote",
                    url=link,
                    source="upwork",
                    salary=budget,
                    job_type="Freelance",
                    tags=[q, "freelance"],
                    is_remote=True,
                ))
        except ET.ParseError:
            pass
    log.info(f"Upwork: {len(jobs)} jobs")
    return jobs


# ── Freelancer.com RSS ────────────────────────────────────────
FREELANCER_QUERIES = [
    "cybersecurity", "penetration-testing", "ethical-hacking",
    "network-security", "security-audit",
]


def _fetch_freelancer() -> list[Job]:
    jobs = []
    for q in FREELANCER_QUERIES:
        url = f"https://www.freelancer.com/rss/category/projects/{q}"
        xml = get_text(url, headers=_HEADERS)
        if not xml:
            continue
        try:
            root = ET.fromstring(xml)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                if not title or not link:
                    continue
                jobs.append(Job(
                    title=title,
                    company="Freelancer Client",
                    location="Remote",
                    url=link,
                    source="freelancer",
                    job_type="Freelance",
                    tags=[q, "freelance"],
                    is_remote=True,
                ))
        except ET.ParseError:
            pass
    log.info(f"Freelancer.com: {len(jobs)} jobs")
    return jobs


# ── Khamsat (خمسات) ───────────────────────────────────────────
KHAMSAT_URLS = [
    "https://khamsat.com/technology/cybersecurity?format=rss",
    "https://khamsat.com/technology/networking?format=rss",
]


def _fetch_khamsat() -> list[Job]:
    jobs = []
    for url in KHAMSAT_URLS:
        xml = get_text(url, headers=_HEADERS)
        if not xml:
            continue
        try:
            root = ET.fromstring(xml)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                if not title or not link:
                    continue
                jobs.append(Job(
                    title=title,
                    company="خمسات",
                    location="Remote",
                    url=link,
                    source="khamsat",
                    job_type="Freelance",
                    tags=["خمسات", "cybersecurity", "freelance"],
                    is_remote=True,
                ))
        except ET.ParseError:
            pass
    log.info(f"Khamsat: {len(jobs)} jobs")
    return jobs


# ── Mustaqil / Mostaql (مستقل) ───────────────────────────────
MUSTAQIL_URLS = [
    "https://www.mostaql.com/projects/rss?category=information-technology&q=cybersecurity",
    "https://www.mostaql.com/projects/rss?category=information-technology&q=security",
    "https://www.mostaql.com/projects/rss?category=information-technology&q=penetration",
    "https://www.mostaql.com/projects/rss?category=information-technology&q=%D8%A3%D9%85%D9%86",
]


def _fetch_mustaqil() -> list[Job]:
    jobs = []
    for url in MUSTAQIL_URLS:
        xml = get_text(url, headers=_HEADERS)
        if not xml:
            continue
        try:
            root = ET.fromstring(xml)
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                if not title or not link:
                    continue
                jobs.append(Job(
                    title=title,
                    company="مستقل",
                    location="Remote",
                    url=link,
                    source="mustaqil",
                    job_type="Freelance",
                    tags=["مستقل", "cybersecurity", "freelance"],
                    is_remote=True,
                ))
        except ET.ParseError:
            pass
    log.info(f"Mustaqil: {len(jobs)} jobs")
    return jobs


def fetch_freelance() -> list[Job]:
    """Aggregate all freelance platforms."""
    jobs = []
    for fetcher in [_fetch_upwork, _fetch_freelancer, _fetch_khamsat, _fetch_mustaqil]:
        try:
            jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"Freelance sub-fetcher {fetcher.__name__} failed: {e}")
    return jobs
