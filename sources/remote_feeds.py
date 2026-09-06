"""
sources/remote_feeds.py — v79 keyless remote bundle.

One SourceSpec ("remote_feeds") fronting five public, keyless remote-job
surfaces: RemoteOK (JSON API), Remotive (JSON API), We Work Remotely (RSS),
Working Nomads (JSON with RSS fallback), Arbeitnow (JSON API).

Design rules (accuracy-first):
  * Per-feed isolation: one dead feed logs at debug and never affects the
    other four — a bundle must not inherit a single endpoint's failure.
  * Honest dates only: feeds that stamp no date stay dateless (neutral
    freshness, ranked after dated jobs). Nothing is ever backdated to now().
  * No relevance filtering here: the shared cyber pipeline (models +
    ai_filter + evidence gates) owns acceptance. This module only fetches.
  * Jobs are stamped source_key="remote_feeds" (one health/quarantine state,
    one priority rank) while keeping the origin feed in ``source`` and tags
    for auditability.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

from models import Job
from sources.http_utils import get_json, get_text
from sources.marketplace_sources import SourceResult

log = logging.getLogger(__name__)


def _stamp(jobs: list | None, *, source_key: str) -> list[Job]:
    """Keep title+URL rows, stamp the bundle key, never invent fields."""
    out: list[Job] = []
    for job in jobs or []:
        try:
            if not getattr(job, "title", "") or not getattr(job, "url", ""):
                continue
            job.source_key = source_key
            if not getattr(job, "content_type", ""):
                job.content_type = "job_listing"
            out.append(job)
        except Exception:  # noqa: BLE001 — one bad row never kills the feed
            continue
    return out


def _parse_iso(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _feed_remoteok() -> list[Job]:
    data = get_json(
        "https://remoteok.com/api",
        headers={"User-Agent": "CyberJobsBot/1.0"},
        timeout=12, max_retries=0,
    )
    if not data or not isinstance(data, list):
        return []
    jobs: list[Job] = []
    for item in data:
        if not isinstance(item, dict) or "id" not in item:
            continue  # first entry is metadata
        jobs.append(Job(
            title=item.get("position", "") or "",
            company=item.get("company", "") or "",
            location=item.get("location", "") or "Remote",
            url=item.get("url", "") or f"https://remoteok.com/remote-jobs/{item.get('id', '')}",
            source="remoteok",
            tags=list(item.get("tags", []) or []),
            is_remote=True,
        ))
    return jobs


def _feed_remotive() -> list[Job]:
    jobs: list[Job] = []
    for cat in ("software-dev", "devops-sysadmin"):
        data = get_json(
            "https://remotive.com/api/remote-jobs",
            params={"category": cat, "limit": 50},
            timeout=12, max_retries=0,
        )
        if not data or "jobs" not in data:
            continue
        for item in data["jobs"]:
            jobs.append(Job(
                title=item.get("title", "") or "",
                company=item.get("company_name", "") or "",
                location=item.get("candidate_required_location", "") or "Anywhere",
                url=item.get("url", "") or "",
                source="remotive",
                salary=item.get("salary", "") or "",
                job_type=(item.get("job_type", "") or "").replace("_", " ").title(),
                tags=[item.get("category", "")] if item.get("category") else [],
                is_remote=True,
                posted_date=_parse_iso(item.get("publication_date") or item.get("created_at") or ""),
            ))
    return jobs


def _feed_wwr() -> list[Job]:
    jobs: list[Job] = []
    feeds = {
        "DevOps-SysAdmin": "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
        "Full-Stack": "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    }
    for category, url in feeds.items():
        xml_text = get_text(url, timeout=12, max_retries=0)
        if not xml_text:
            continue
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            continue
        for item in root.findall(".//item"):
            title_raw = item.findtext("title", "") or ""
            if ": " in title_raw:
                company, title = title_raw.split(": ", 1)
            else:
                company, title = "", title_raw
            pub = item.findtext("pubDate", "") or ""
            posted = None
            if pub:
                try:
                    posted = parsedate_to_datetime(pub).replace(tzinfo=None)
                except (TypeError, ValueError):
                    posted = None
            jobs.append(Job(
                title=title.strip(), company=company.strip(), location="Remote",
                url=(item.findtext("link", "") or "").strip(), source="wwr",
                tags=[category], is_remote=True, posted_date=posted,
            ))
    return jobs


def _feed_workingnomads() -> list[Job]:
    data = get_json("https://www.workingnomads.com/api/exposed_jobs/", timeout=12, max_retries=0)
    jobs: list[Job] = []
    if isinstance(data, list):
        for item in data:
            cat = (item.get("category_name", "") or "").lower()
            if cat not in ("development", "dev", "sysadmin", "devops", "security"):
                continue
            jobs.append(Job(
                title=item.get("title", "") or "",
                company=item.get("company_name", "") or "",
                location="Remote",
                url=item.get("url", "") or item.get("external_url", "") or "",
                source="workingnomads",
                tags=[cat] if cat else [],
                is_remote=True,
            ))
        return jobs
    xml_text = get_text(
        "https://www.workingnomads.com/jobsrss?category=development",
        timeout=12, max_retries=0,
    )
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    for item in root.findall(".//item"):
        title = item.findtext("title", "") or ""
        company = ""
        if " at " in title:
            title, company = (part.strip() for part in title.rsplit(" at ", 1))
        jobs.append(Job(
            title=title, company=company, location="Remote",
            url=(item.findtext("link", "") or "").strip(), source="workingnomads",
            tags=[item.findtext("category", "") or ""], is_remote=True,
        ))
    return jobs


def _feed_arbeitnow() -> list[Job]:
    data = get_json("https://www.arbeitnow.com/api/job-board-api", timeout=12, max_retries=0)
    if not data or "data" not in data:
        return []
    jobs: list[Job] = []
    for item in data["data"]:
        created = item.get("created_at")
        posted = None
        if created is not None:
            try:
                posted = datetime.fromtimestamp(int(created))
            except (TypeError, ValueError, OSError):
                posted = _parse_iso(created)
        jobs.append(Job(
            title=item.get("title", "") or "",
            company=item.get("company_name", "") or "",
            location=item.get("location", "") or "",
            url=item.get("url", "") or "",
            source="arbeitnow",
            tags=list(item.get("tags", []) or []),
            is_remote=bool(item.get("remote", False)),
            posted_date=posted,
        ))
    return jobs


_FEEDS: tuple[tuple[str, object], ...] = (
    ("remoteok", _feed_remoteok),
    ("remotive", _feed_remotive),
    ("wwr", _feed_wwr),
    ("workingnomads", _feed_workingnomads),
    ("arbeitnow", _feed_arbeitnow),
)


def fetch_remote_feeds() -> SourceResult:
    """Fetch all five keyless remote feeds with per-feed isolation."""
    all_jobs: list[Job] = []
    attempted = 0
    failed = 0
    for feed_name, feeder in _FEEDS:
        try:
            rows = _stamp(feeder(), source_key="remote_feeds")
        except Exception as exc:  # noqa: BLE001 — isolation boundary
            failed += 1
            log.debug("remote_feeds/%s unavailable: %s", feed_name, exc)
            continue
        attempted += 1
        all_jobs.extend(rows)
    if all_jobs:
        log.info("remote_feeds: %d jobs from %d/%d feeds", len(all_jobs), attempted, len(_FEEDS))
        return SourceResult(all_jobs, "success", "direct")
    if attempted > 0:
        # Feeds answered but carried no usable rows this run — honest empty,
        # never a failure streak.
        return SourceResult(
            [], status="empty", transport="direct",
            error_code="no_security_listings_in_feeds",
        )
    return SourceResult(
        [], status="blocked", transport="direct",
        error_code="remote_feeds_unreachable",
    )
