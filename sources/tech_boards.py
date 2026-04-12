"""
Tech boards — moved Greenhouse + Lever + Dice here.
Dice: uses official Dice API (replaces dead seibert.group proxy).
Greenhouse/Lever: slugs updated to working ones only.
"""

import logging
import re
from models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# Greenhouse and Lever are now in cybersec_boards.py to avoid duplication.
# tech_boards.py focuses on Dice only (Greenhouse/Lever duplicated = skipped).


def _fetch_dice():
    """
    Dice.com — official search API (seibert.group proxy is dead since DNS failed).
    Fetches remote security jobs only.
    """
    jobs = []
    seen = set()
    queries = [
        "cybersecurity engineer", "SOC analyst", "penetration tester",
        "security architect", "cloud security engineer", "devsecops",
        "malware analyst", "threat intelligence analyst", "detection engineer",
        "application security engineer", "information security analyst",
    ]
    for q in queries:
        # Try Dice's official search endpoint
        url    = "https://job-search-api.dice.com/v1/dice.com/search"
        params = {
            "q": q,
            "countryCode2": "US",
            "radius": "30",
            "radiusUnit": "mi",
            "page": "1",
            "pageSize": "20",
            "filters.workplaceTypes": "Remote",
            "languageCode": "en",
        }
        data = get_json(url, params=params, headers=HEADERS)
        if not data:
            # Fallback: Dice RSS
            import xml.etree.ElementTree as ET
            from sources.http_utils import get_text
            rss_url = f"https://www.dice.com/jobs/q-{q.replace(' ', '_')}-jobs.rss"
            xml = get_text(rss_url, headers=HEADERS)
            if xml:
                try:
                    root = ET.fromstring(xml)
                    for item in root.findall(".//item"):
                        title = item.findtext("title", "").strip()
                        link  = item.findtext("link", "").strip()
                        if title and link and link not in seen:
                            seen.add(link)
                            jobs.append(Job(
                                title=title, company="Dice Employer",
                                location="Remote", url=link,
                                source="dice", tags=[q, "dice"],
                                is_remote=True,
                            ))
                except ET.ParseError:
                    pass
            continue

        items = (data.get("data", {}).get("jobs") or data.get("jobs") or [])
        for item in items:
            title    = (item.get("title") or item.get("name") or "").strip()
            job_url  = item.get("applyDetailUrl") or item.get("url") or ""
            company  = (item.get("companyName") or item.get("company") or "").strip()
            location = (item.get("locationStr") or item.get("location") or "Remote").strip()
            is_remote = "remote" in location.lower()
            if not title or job_url in seen:
                continue
            seen.add(job_url)
            jobs.append(Job(
                title=title, company=company,
                location=location, url=job_url,
                source="dice", tags=[q, "dice"],
                is_remote=is_remote,
            ))
    log.info(f"Dice: {len(jobs)} jobs")
    return jobs


def fetch_tech_boards() -> list[Job]:
    """Tech boards — Dice only (Greenhouse/Lever in cybersec_boards.py)."""
    jobs = []
    for fetcher in [_fetch_dice]:
        try:
            jobs.extend(fetcher())
        except Exception as e:
            log.warning(f"tech_boards: {fetcher.__name__} failed: {e}")
    return jobs
