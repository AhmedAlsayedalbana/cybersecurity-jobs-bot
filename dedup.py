"""
Deduplication: tracks seen job IDs to avoid re-sending.

v28 FIXES:
  - MEMORY_DAYS: 7 → 3 (faster expiry, less bloat)
  - Removed triple-key (unique_id + url_id + url:md5) → now dual-key (unique_id + url_id)
    The md5 key was the main cause of bloat: each job stored 3 keys instead of 2
  - Added smart_expire(): if new_jobs == 0, expire everything older than 1 day
    This prevents the "seen everything, send nothing" deadlock
"""

import json
import os
import logging
from datetime import datetime, timedelta
from models import Job
from config import SEEN_JOBS_FILE

log = logging.getLogger(__name__)

MEMORY_DAYS = 7  # v32: restored to 7 — 3 days was causing re-sending of old jobs


def load_seen_ids(path: str = SEEN_JOBS_FILE) -> dict:
    """Load previously seen job IDs with timestamps. Returns {job_id: timestamp_iso}."""
    if not os.path.exists(path):
        log.info("No seen_jobs file found — starting fresh.")
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            now_iso = datetime.now().isoformat()
            log.info(f"Migrating {len(data)} legacy IDs to timestamped format.")
            return {jid: now_iso for jid in data}
        log.info(f"Loaded {len(data)} seen job IDs.")
        return data
    except (json.JSONDecodeError, IOError) as e:
        log.warning(f"Error reading seen_jobs: {e} — starting fresh.")
        return {}


def save_seen_ids(seen_dict: dict, path: str = SEEN_JOBS_FILE) -> None:
    """Save seen job IDs, removing entries older than MEMORY_DAYS."""
    now    = datetime.now()
    cutoff = now - timedelta(days=MEMORY_DAYS)
    cleaned = {}
    for jid, ts_iso in seen_dict.items():
        try:
            if datetime.fromisoformat(ts_iso) > cutoff:
                cleaned[jid] = ts_iso
        except (ValueError, TypeError):
            cleaned[jid] = now.isoformat()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, ensure_ascii=False, indent=2)
        log.info(f"Saved {len(cleaned)} seen job IDs (cleaned {len(seen_dict) - len(cleaned)} old ones).")
    except IOError as e:
        log.error(f"Error saving seen_jobs: {e}")


def smart_expire(seen_dict: dict, new_jobs_count: int) -> dict:
    """
    If new_jobs == 0 after dedup, we're stuck in a 'seen everything' deadlock.
    Force-expire entries older than 1 day so next run gets fresh jobs.
    This happens when the same job pool repeats across consecutive runs.
    """
    if new_jobs_count > 0:
        return seen_dict  # No deadlock — no action needed

    cutoff = datetime.now() - timedelta(days=1)
    before = len(seen_dict)
    freed = {jid: ts for jid, ts in seen_dict.items()
             if datetime.fromisoformat(ts) > cutoff}
    freed_count = before - len(freed)
    if freed_count > 0:
        log.warning(f"smart_expire: 0 new jobs detected — freed {freed_count} seen IDs (>1 day old). Next run will re-check them.")
    return freed


def deduplicate(jobs: list[Job], seen_dict: dict) -> list[Job]:
    """
    Return only jobs not already in seen_dict.
    Uses dual-key dedup: title+company AND url_id.
    """
    new_jobs = []
    batch_ids: set[str] = set()

    for job in jobs:
        uid    = job.unique_id
        url_id = getattr(job, "url_id", "")

        if uid in seen_dict or uid in batch_ids:
            continue
        if url_id and (url_id in seen_dict or url_id in batch_ids):
            continue

        batch_ids.add(uid)
        if url_id:
            batch_ids.add(url_id)
        new_jobs.append(job)

    log.info(f"Dedup: {len(jobs)} total → {len(new_jobs)} new jobs.")
    return new_jobs


def mark_as_seen(jobs: list[Job], seen_dict: dict) -> dict:
    """Add unique_id and url_id to seen dict with current timestamp."""
    now_iso = datetime.now().isoformat()
    for job in jobs:
        seen_dict[job.unique_id] = now_iso
        url_id = getattr(job, "url_id", "")
        if url_id:
            seen_dict[url_id] = now_iso
    return seen_dict


def deduplicate_sent(sent_urls: set, jobs: list[Job], seen_dict: dict) -> dict:
    """Mark actually-sent jobs as seen. Only called with jobs that were sent."""
    now_iso     = datetime.now().isoformat()
    sent_url_set = set(sent_urls)
    for job in jobs:
        if job.url in sent_url_set:
            seen_dict[job.unique_id] = now_iso
            url_id = getattr(job, "url_id", "")
            if url_id:
                seen_dict[url_id] = now_iso
    return seen_dict
