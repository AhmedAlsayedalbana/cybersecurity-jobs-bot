"""Regional secondary boards (no-login): Wuzzuf, Freelancer, Mostaql."""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
import requests

import config
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

_SECURITY_TERMS = [
    "cybersecurity", "cyber security", "information security", "infosec",
    "security analyst", "security engineer", "soc", "grc", "pentest",
    "penetration", "appsec", "cloud security", "network security",
    "malware", "dfir", "incident response", "threat intelligence",
]
_SECURITY_TERMS = config.sanitize_keywords(_SECURITY_TERMS, min_len=3)


def _is_security(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in _SECURITY_TERMS)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _direct_get_text(url: str, timeout: int = 10, retries: int = 2) -> str | None:
    """
    Force direct connection (no proxy pool) for sources that frequently fail via proxy auth.
    """
    session = requests.Session()
    session.headers.update(_H)
    session.proxies = {}
    for attempt in range(retries + 1):
        try:
            resp = session.get(url, timeout=timeout)
            if resp.status_code == 503 and attempt < retries:
                time.sleep(1.2 + attempt)
                continue
            resp.raise_for_status()
            return resp.text
        except requests.RequestException:
            if attempt >= retries:
                return None
            time.sleep(0.8 + attempt)
    return None


def _fetch_wuzzuf_html() -> list[Job]:
    if not config.ENABLE_SOURCE_WUZZUF:
        return []
    queries = [
        "cybersecurity",
        "information security",
        "soc analyst",
        "penetration tester",
        "grc",
    ]
    jobs: list[Job] = []
    seen: set[str] = set()
    start = time.time()
    budget = 45
    for q in queries:
        if time.time() - start > budget:
            break
        url = f"https://wuzzuf.net/search/jobs/?q={urllib.parse.quote(q)}&country=Egypt"
        html = get_text(url, headers=_H, timeout=10, max_retries=1)
        if not html:
            continue

        # Job cards are stable enough using /jobs/p/ links.
        for href, anchor_text in re.findall(
            r'<a[^>]+href="(/jobs/p/[^"]+)"[^>]*>(.*?)</a>',
            html,
            re.IGNORECASE | re.DOTALL,
        ):
            title = _clean_text(anchor_text)
            if not title or not _is_security(title):
                continue
            full_url = urllib.parse.urljoin("https://wuzzuf.net", href)
            if full_url in seen:
                continue
            seen.add(full_url)
            jobs.append(Job(
                title=title,
                company="Wuzzuf",
                location="Egypt",
                url=full_url,
                source="wuzzuf",
                tags=["wuzzuf", "egypt", "regional-board"],
            ))
        time.sleep(0.3)
    log.info(f"Wuzzuf HTML: {len(jobs)} jobs")
    return jobs


def _fetch_freelancer_security() -> list[Job]:
    if not config.ENABLE_SOURCE_FREELANCER:
        return []
    jobs: list[Job] = []
    seen: set[str] = set()

    # RSS contains latest projects (not only security), so we filter aggressively.
    rss = _direct_get_text("https://www.freelancer.com/rss.xml", timeout=12, retries=1)
    if not rss:
        rss = get_text("https://www.freelancer.com/rss.xml", headers=_H, timeout=10, max_retries=1)
    if rss:
        try:
            rss = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", rss)
            root = ET.fromstring(rss)
            for item in root.findall(".//item"):
                title = _clean_text(item.findtext("title", ""))
                link = _clean_text(item.findtext("link", ""))
                desc = _clean_text(item.findtext("description", ""))
                if not title or not link or link in seen:
                    continue
                if not _is_security(f"{title} {desc}"):
                    continue
                seen.add(link)
                jobs.append(Job(
                    title=title,
                    company="Freelancer Client",
                    location="Remote",
                    url=link,
                    source="freelancer",
                    job_type="Freelance",
                    tags=["freelancer", "gig", "regional-board"],
                    is_remote=True,
                    description=desc[:400],
                ))
        except ET.ParseError:
            pass

    # Category page gives richer security-only set.
    html = _direct_get_text("https://www.freelancer.com/jobs/network-security/", timeout=12, retries=1)
    if not html:
        html = get_text("https://www.freelancer.com/jobs/network-security/", headers=_H, timeout=10, max_retries=1)
    if html:
        for href, anchor_text in re.findall(
            r'<a[^>]+href="(/projects/[^"]+)"[^>]*>(.*?)</a>',
            html,
            re.IGNORECASE | re.DOTALL,
        ):
            title = _clean_text(anchor_text)
            if not title or title.lower().startswith("bid now"):
                continue
            if not _is_security(title):
                continue
            full_url = urllib.parse.urljoin("https://www.freelancer.com", href)
            if full_url in seen:
                continue
            seen.add(full_url)
            jobs.append(Job(
                title=title,
                company="Freelancer Client",
                location="Remote",
                url=full_url,
                source="freelancer",
                job_type="Freelance",
                tags=["freelancer", "gig", "regional-board"],
                is_remote=True,
            ))
    log.info(f"Freelancer: {len(jobs)} jobs")
    return jobs


def _fetch_mostaql_rss() -> list[Job]:
    if not config.ENABLE_SOURCE_MOSTAQL:
        return []
    jobs: list[Job] = []
    seen: set[str] = set()
    xml = _direct_get_text("https://mostaql.com/rss", timeout=12, retries=2)
    if not xml:
        xml = get_text("https://mostaql.com/rss", headers=_H, timeout=10, max_retries=1)
    if not xml:
        return jobs
    try:
        xml = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", xml)
        root = ET.fromstring(xml)
    except ET.ParseError:
        log.warning("Mostaql RSS parse failed")
        return jobs

    for item in root.findall(".//item"):
        title = _clean_text(item.findtext("title", ""))
        link = _clean_text(item.findtext("link", ""))
        desc = _clean_text(item.findtext("description", ""))
        if not link or link in seen:
            continue
        if not _is_security(f"{title} {desc}"):
            continue
        seen.add(link)
        jobs.append(Job(
            title=title or "Security Project",
            company="Mostaql Client",
            location="Remote",
            url=link,
            source="mostaql",
            job_type="Freelance",
            tags=["mostaql", "gig", "regional-board"],
            is_remote=True,
            description=desc[:400],
        ))
    log.info(f"Mostaql RSS: {len(jobs)} jobs")
    return jobs


def fetch_regional_boards() -> list[Job]:
    """Secondary boards after LinkedIn; no-login only."""
    jobs: list[Job] = []
    for fetcher in (_fetch_wuzzuf_html, _fetch_freelancer_security, _fetch_mostaql_rss):
        try:
            jobs.extend(fetcher())
        except Exception as exc:
            log.warning(f"regional_boards: {fetcher.__name__} failed: {exc}")
    return jobs
