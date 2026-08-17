"""
sources/gulf_monster.py — v46
Monster Gulf RSS connector.
Fix: pubDate parsed as UTC-naive to avoid offset-aware subtraction bug.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import NamedTuple

from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)
SOURCE_NAME = "monstergulf"

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}


class _FeedSpec(NamedTuple):
    url: str
    geo_hint: str


_FEEDS: list[_FeedSpec] = [
    _FeedSpec("https://www.monstergulf.com/en-ae/jobs/cybersecurity?format=rss",       "gulf"),
    _FeedSpec("https://www.monstergulf.com/en-sa/jobs/cybersecurity?format=rss",       "gulf"),
    _FeedSpec("https://www.monstergulf.com/en-ae/jobs/information-security?format=rss","gulf"),
    _FeedSpec("https://www.monstergulf.com/en-ae/jobs/network-security?format=rss",    "gulf"),
    _FeedSpec("https://www.monstergulf.com/en-ae/jobs/penetration-testing?format=rss", "gulf"),
]


def _parse_rss_date(date_str: str) -> datetime | None:
    """Parse RFC 2822 date → UTC-naive datetime."""
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _clean_xml(raw: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", raw)


def _fetch_feed(spec: _FeedSpec, seen_urls: set[str]) -> list[Job]:
    xml_raw = get_text(spec.url, headers=_H)
    if not xml_raw:
        return []
    try:
        root = ET.fromstring(_clean_xml(xml_raw))
    except ET.ParseError as exc:
        log.debug("Monster Gulf RSS parse error (%s): %s", spec.url, exc)
        return []

    jobs: list[Job] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link  = (item.findtext("link")  or "").strip()
        desc  = (item.findtext("description") or "").strip()
        if not title or not link or link in seen_urls:
            continue
        seen_urls.add(link)

        company_raw = item.findtext("author") or ""
        if not company_raw:
            m = re.search(r"<strong>(.*?)</strong>", desc)
            company_raw = m.group(1) if m else "Monster Gulf"
        company = re.sub(r"<[^>]+>", "", company_raw).strip() or "Monster Gulf"

        location_tag = item.findtext("{http://www.monster.com/}location") or ""
        if not location_tag:
            m = re.search(r"[·\-–|]\s*([A-Za-z\s,]+)$", title)
            location_tag = m.group(1).strip() if m else "Gulf"

        posted_at = _parse_rss_date(item.findtext("pubDate") or "")
        is_remote = "remote" in (title + " " + desc).lower()

        jobs.append(Job(
            title=title,
            company=company,
            location=location_tag or "Gulf",
            url=link,
            source=SOURCE_NAME,
            description=re.sub(r"<[^>]+>", " ", desc)[:500],
            is_remote=is_remote,
            posted_date=posted_at,
            geo_hint=spec.geo_hint,
            original_source="Monster Gulf",
            tags=["monstergulf", "gulf"],
        ))
    return jobs


def fetch_gulf_monster() -> list[Job]:
    all_jobs: list[Job] = []
    seen_urls: set[str] = set()
    for spec in _FEEDS:
        try:
            batch = _fetch_feed(spec, seen_urls)
            all_jobs.extend(batch)
        except Exception as exc:
            log.warning("gulf_monster: feed %s failed: %s", spec.url, exc)
    log.info("Monster Gulf total: %d raw jobs", len(all_jobs))
    return all_jobs
