"""
sources/greenhouse_expanded.py  — v46
Greenhouse API connector: Big Tech + SaaS + Cybersec vendors.

v46 FIXES:
  • All Lever slugs removed (all returned 404 — vendors moved to Greenhouse/Workday).
  • Lever companies migrated to their confirmed Greenhouse slugs.
  • datetime parsed as UTC-naive to fix offset-aware subtraction bug in models.py.
  • Timeout budget respected via SOURCE_TIMEOUT env var.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import NamedTuple

import requests

import config
from models import Job

log = logging.getLogger(__name__)

_H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

SOURCE_NAME = "greenhouse_expanded"
SOURCE_TIMEOUT = int(getattr(config, "GREENHOUSE_EXPANDED_TIMEOUT_SEC", 480))


class BoardEntry(NamedTuple):
    slug: str
    name: str


def get_json(url: str, *, headers: dict | None = None, timeout: int = 12) -> dict | None:
    """Fetch Greenhouse JSON while preserving status details for stale-board logging."""
    resp = requests.get(url, headers=headers, timeout=timeout)
    if resp.status_code == 404:
        return {"_greenhouse_status": 404}
    if resp.status_code != 200:
        return {"_greenhouse_status": resp.status_code}
    return resp.json()


# ── Tier 1A: Big Tech ────────────────────────────────────────────────────
# ── Tier 1A: Security-heavy Tech companies (reduced to those with real cyber teams)
# Removed: Airbnb, Lyft, Figma, Pinterest, Instacart, Squarespace, Twitch, Duolingo, Asana
# These generate thousands of non-cyber jobs (>95% noise)
_GREENHOUSE_BIG_TECH: list[BoardEntry] = [
    BoardEntry("datadog",     "Datadog"),          # Observability+security platform
    BoardEntry("mongodb",     "MongoDB"),          # Has dedicated security team
    BoardEntry("elastic",     "Elastic"),          # SIEM/security analytics
    BoardEntry("coinbase",    "Coinbase"),         # Large security team (crypto)
    BoardEntry("databricks",  "Databricks"),       # Cloud data+security
    BoardEntry("fastly",      "Fastly"),           # CDN/WAF/security
    BoardEntry("hubspot",     "HubSpot"),          # Has security engineering roles
    # Removed low-signal: stripe, airbnb, lyft, dropbox, figma, robinhood,
    # pinterest, reddit, instacart, asana, squarespace, twitch, duolingo
]

# ── Tier 1B: SaaS ────────────────────────────────────────────────────────
_GREENHOUSE_SAAS: list[BoardEntry] = [
    BoardEntry("gitlab",    "GitLab"),
    BoardEntry("postman",   "Postman"),
    BoardEntry("twilio",    "Twilio"),
    BoardEntry("brex",      "Brex"),
    BoardEntry("gusto",     "Gusto"),
    BoardEntry("lattice",   "Lattice"),
    BoardEntry("intercom",  "Intercom"),
    BoardEntry("mercury",   "Mercury"),
    BoardEntry("algolia",   "Algolia"),
    BoardEntry("okta",      "Okta"),
    BoardEntry("bitwarden", "Bitwarden"),
    BoardEntry("netlify",   "Netlify"),
    BoardEntry("airtable",  "Airtable"),
]

# ── Tier 1C: Cybersec vendors (Greenhouse) ───────────────────────────────
# Includes former Lever companies that migrated to Greenhouse.
_GREENHOUSE_CYBERSEC: list[BoardEntry] = [
    # ── Core cybersecurity vendors ────────────────────────────────────────
    BoardEntry("abnormalsecurity",  "Abnormal Security"),
    BoardEntry("orca",              "Orca Security"),
    BoardEntry("huntress",          "Huntress"),
    BoardEntry("axonius",           "Axonius"),
    BoardEntry("exabeam",           "Exabeam"),
    BoardEntry("torq",              "Torq"),
    BoardEntry("sentinellabs",      "SentinelOne"),
    BoardEntry("rubrik",            "Rubrik"),
    # ── Additional security vendors (added v53) ───────────────────────────
    # v54: lacework/snyk/cyberark/secureworks/rapid7/tenable/qualys/vectra/
    # darktrace/armis/securonix/logrhythm/attackiq removed — all consistently
    # returned HTTP 404 (moved off Greenhouse or use a different board token).
    # Re-add once the correct board slug is confirmed for each.
    BoardEntry("beyondtrust",       "BeyondTrust"),
    BoardEntry("safebreach",        "SafeBreach"),
    BoardEntry("cymulate",          "Cymulate"),
    BoardEntry("cybereason",        "Cybereason"),
    # Note: zscaler removed - was timing out in logs
]


def _parse_posted_at(raw_ts: str | None) -> datetime | None:
    """Parse ISO 8601 timestamp → UTC-naive datetime (avoids timezone subtraction bug)."""
    if not raw_ts:
        return None
    try:
        dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _fetch_greenhouse_board(entry: BoardEntry) -> list[Job]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{entry.slug}/jobs?content=true"
    try:
        data = get_json(url, headers=_H, timeout=12)
        status = data.get("_greenhouse_status") if isinstance(data, dict) else None
        if status == 404:
            log.warning("Greenhouse slug returned 404: %s (%s)", entry.slug, entry.name)
            return []
        if status:
            log.warning("Greenhouse slug returned HTTP %s: %s (%s)", status, entry.slug, entry.name)
            return []
    except Exception as exc:
        log.warning("Greenhouse slug failed: %s (%s): %s", entry.slug, entry.name, exc)
        return []
    if not data or "jobs" not in data:
        return []

    jobs: list[Job] = []
    for item in data["jobs"]:
        title   = (item.get("title") or "").strip()
        job_url = (item.get("absolute_url") or "").strip()
        if not title or not job_url:
            continue

        loc_raw  = item.get("location", {})
        location = (loc_raw.get("name", "") if isinstance(loc_raw, dict) else "") or ""
        is_remote = "remote" in location.lower()
        posted_at = _parse_posted_at(item.get("created_at"))

        jobs.append(Job(
            title=title,
            company=entry.name,
            location=location or "Not specified",
            url=job_url,
            source=SOURCE_NAME,
            is_remote=is_remote,
            posted_date=posted_at,
            original_source=f"Greenhouse / {entry.name}",
            tags=["greenhouse", entry.name.lower().replace(" ", "_")],
        ))
    return jobs


def _run_batch(boards: list[BoardEntry], label: str, *, budget_sec: float = 90.0) -> list[Job]:
    """Fetch all boards in a batch with a per-batch budget to avoid blocking the full run."""
    all_jobs: list[Job] = []
    batch_start = time.time()
    for entry in boards:
        if time.time() - batch_start > budget_sec:
            log.info("Greenhouse %s: batch budget %.0fs exhausted after %d boards", label, budget_sec, len(all_jobs))
            break
        try:
            jobs = _fetch_greenhouse_board(entry)
            all_jobs.extend(jobs)
            if jobs:
                log.debug("Greenhouse %s / %s: %d", label, entry.name, len(jobs))
        except Exception as exc:
            log.debug("Greenhouse %s / %s failed: %s", label, entry.name, exc)
    log.info("Greenhouse %s: %d raw jobs", label, len(all_jobs))
    return all_jobs


def fetch_greenhouse_expanded() -> list[Job]:
    """Fetch Greenhouse boards.
    v53: Cybersec vendors first (always full), then BigTech+SaaS with 60s budgets each.
    """
    _start = time.time()
    all_jobs: list[Job] = []

    # Run order: Cybersec (highest priority, always full) → BigTech → SaaS
    batches = [
        ("Cybersec", _GREENHOUSE_CYBERSEC, 120.0),  # dedicated cybersec vendors — always full
        ("BigTech",  _GREENHOUSE_BIG_TECH,  60.0),  # only security-heavy tech companies now
        ("SaaS",     _GREENHOUSE_SAAS,      60.0),  # limited SaaS companies
    ]

    for label, boards, budget in batches:
        if time.time() - _start > SOURCE_TIMEOUT:
            log.warning("greenhouse_expanded: global timeout at %s batch", label)
            break
        all_jobs.extend(_run_batch(boards, label, budget_sec=budget))

    log.info("greenhouse_expanded total: %d raw jobs (%.1fs)",
             len(all_jobs), time.time() - _start)
    return all_jobs
