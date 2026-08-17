"""Exact-identity deduplication for job postings.

Jobs are duplicates only when they resolve to the same canonical posting URL
or provider job ID. Title, company, location, and fuzzy fingerprints are
stored for audit only and never decide whether a posting is dropped.
"""

import re
import logging
from collections import Counter
from datetime import datetime
from models import Job
from config import DAILY_SEND_HOURS, GLOBAL_DEDUP_HOURS, SEEN_JOBS_FILE
from database import JobsDB, get_db

log = logging.getLogger(__name__)

MEMORY_DAYS = 5

_db: JobsDB | None = None


def _get_db() -> JobsDB:
    global _db
    if _db is None:
        _db = get_db()
    return _db


def _normalize(text: str) -> str:
    text = text.lower().strip()
    noise = r"\b(inc|ltd|llc|corp|co|the|a|an|of|for|at|in|and|group|company|technologies|services)\b"
    text = re.sub(noise, " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _job_fingerprint(job: Job) -> str:
    title = _normalize(re.sub(r"\s*[-��]{1,2}\s*\d{1,3}\s*$", "", job.title or ""))
    company = _normalize(job.company)
    city    = _normalize(job.location.split(",")[0]) if job.location else ""
    return f"{title}||{company}||{city}"


def _job_identity(job: Job) -> str:
    """Return an exact provider identity; never fall back to title/company."""
    url_id = getattr(job, "url_id", "") or ""
    if url_id:
        return url_id
    raw_url = getattr(job, "canonical_url", "") or getattr(job, "url", "") or ""
    return re.sub(r"[?#].*$", "", raw_url.lower().rstrip("/"))


def load_seen_ids(path: str = SEEN_JOBS_FILE) -> dict:
    db   = _get_db()
    seen_hours = MEMORY_DAYS * 24
    seen = db.load_seen_ids(window_hours=seen_hours)
    log.info(f"[dedup] Loaded {len(seen)} sent job IDs from SQLite ({MEMORY_DAYS}d window).")
    return seen


def save_seen_ids(seen_dict: dict, path: str = SEEN_JOBS_FILE) -> None:
    db = _get_db()
    db.cleanup_old(days=MEMORY_DAYS)
    summary = db.get_stats_summary()
    log.info(
        f"[dedup] DB: {summary['total_seen']} total seen, "
        f"{summary['total_sent']} sent."
    )


def smart_expire(seen_dict: dict, new_jobs_count: int) -> dict:
    """
    v52 FIX: was a complete no-op causing zero-recovery to always fail silently.
    When 0 new jobs found, expire the oldest 20% of in-memory seen entries
    so the next deduplicate() can let recently-expired candidates through.
    """
    if new_jobs_count > 0:
        return seen_dict
    if not seen_dict:
        return seen_dict
    sorted_items = sorted(seen_dict.items(), key=lambda kv: kv[1])
    drop_n = max(1, len(sorted_items) // 5)
    expired_keys = {k for k, _ in sorted_items[:drop_n]}
    trimmed = {k: v for k, v in seen_dict.items() if k not in expired_keys}
    log.info(
        f"[dedup] smart_expire: 0 new jobs -- expired {drop_n}/{len(seen_dict)} "
        f"oldest in-memory IDs to open recovery window."
    )
    return trimmed


def deduplicate(jobs: list, seen_dict: dict, *, telemetry: Counter | None = None) -> list:
    """
    Exact-identity dedup:
      0. Provider ID for the same LinkedIn post across LinkedIn collectors
      1. Canonical URL / provider job ID within this batch and sent history

    Similar titles or a shared company are deliberately retained as distinct
    opportunities.
    """
    db = _get_db()
    new_jobs   = []
    batch_identities: set[str] = set()
    # Layer 0: track url_ids per source family to prevent same LinkedIn job
    # appearing from both linkedin_hr_hunter AND linkedin_posts AND linkedin etc.
    source_url_ids: dict = {}

    for job in jobs:
        url_id = getattr(job, "url_id", "")
        source = getattr(job, "source", "")
        identity = _job_identity(job)

        # Layer 0: per-source-family dedup (same LinkedIn job ID from different LinkedIn fetchers)
        if url_id and (url_id.startswith("li_job_") or url_id.startswith("li_post_")):
            if url_id in source_url_ids:
                log.debug(f"[dedup] Cross-source dupe (same LinkedIn job): {job.title} � already from {source_url_ids[url_id]}")
                if telemetry is not None:
                    telemetry["duplicate"] += 1
                continue
            source_url_ids[url_id] = source

        # Layer 1: exact provider ID or canonical URL only. `unique_id` is
        # title/company based and must never participate in deduplication.
        if not identity:
            log.debug("[dedup] Missing exact identity; retaining: %s", job.title)
            new_jobs.append(job)
            continue
        if identity in seen_dict:
            if telemetry is not None:
                telemetry["already_sent"] += 1
            continue
        if identity in batch_identities:
            if telemetry is not None:
                telemetry["duplicate"] += 1
            continue
        if db.was_sent_globally_recently(identity, url_id, identity, hours=GLOBAL_DEDUP_HOURS):
            if telemetry is not None:
                telemetry["already_sent"] += 1
            continue
        if db.was_sent_recently(identity, url_id, lane="any", hours=DAILY_SEND_HOURS):
            if telemetry is not None:
                telemetry["already_sent"] += 1
            continue

        batch_identities.add(identity)
        new_jobs.append(job)

    log.info(f"[dedup] {len(jobs)} total -> {len(new_jobs)} new (exact-identity dedup).")
    return new_jobs


def mark_as_seen(jobs: list, seen_dict: dict) -> dict:
    db = _get_db()
    now_iso = datetime.now().isoformat()
    for job in jobs:
        fp = _job_fingerprint(job)
        db.mark_seen(
            job_key=_job_identity(job),
            url_id=getattr(job, "url_id", ""),
            fingerprint=fp,
            title=job.title, company=job.company,
            location=job.location, source=job.source,
            sent=False,
            source_key=getattr(job, "source_key", "") or getattr(job, "source", ""),
            content_type=getattr(job, "content_type", "job_listing"),
            origin_priority=int(getattr(job, "origin_priority", 999) or 999),
        )
        # Do not add unsent jobs to seen_dict:
        # they should stay eligible until sent or stale.
    return seen_dict


def deduplicate_sent(sent_records: list, seen_dict: dict) -> dict:
    """
    Persist successful sends with channel-aware events:
      - per-lane timestamps in jobs table
      - per-channel events in sent_events table (strict 24h channel dedup)
    """
    db = _get_db()
    now_iso = datetime.now().isoformat()
    for job, lane, channel_key in sent_records:
        fp = _job_fingerprint(job)
        url_id = getattr(job, "url_id", "")
        identity = _job_identity(job)
        dedup_key = identity
        db.mark_sent(
            job_key=identity,
            url_id=url_id,
            fingerprint=fp,
            title=job.title, company=job.company,
            location=job.location, source=job.source,
            lane=lane,
            source_key=getattr(job, "source_key", "") or getattr(job, "source", ""),
            content_type=getattr(job, "content_type", "job_listing"),
            origin_priority=int(getattr(job, "origin_priority", 999) or 999),
        )
        db.record_sent_event(
            job_key=identity,
            url_id=url_id,
            channel_key=channel_key,
            lane=lane,
            dedup_key=dedup_key,
        )
        db.record_training_sample(
            dedup_key=dedup_key,
            title=job.title,
            company=job.company,
            location=job.location,
            source=getattr(job, "source_key", "") or job.source,
            content_type=getattr(job, "content_type", "job_listing"),
            description_short=(job.description or "")[:500],
            accepted=True,
            reason=f"sent:{channel_key}",
        )
        if identity:
            seen_dict[identity] = now_iso
        if url_id:
            seen_dict[url_id] = now_iso
    return seen_dict
