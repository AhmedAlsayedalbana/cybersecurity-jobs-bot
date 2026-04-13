"""
Deduplication: tracks seen job IDs to avoid re-sending.
Weekly Memory: keeps history for 7 days.
"""

import json
import os
import logging
from datetime import datetime, timedelta
from models import Job
from config import SEEN_JOBS_FILE

log = logging.getLogger(__name__)

# Memory limit: 7 days
MEMORY_DAYS = 7

def load_seen_ids(path: str = SEEN_JOBS_FILE) -> dict:
    """
    Load previously seen job IDs with timestamps.
    Returns a dict {job_id: timestamp_iso}.
    """
    if not os.path.exists(path):
        log.info("No seen_jobs file found — starting fresh.")
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        # Support legacy format (list) or new format (dict)
        if isinstance(data, list):
            # Migrate old list format to dict with current timestamp
            now_iso = datetime.now().isoformat()
            log.info(f"Migrating {len(data)} legacy IDs to timestamped format.")
            return {jid: now_iso for jid in data}
            
        log.info(f"Loaded {len(data)} seen job IDs.")
        return data
    except (json.JSONDecodeError, IOError) as e:
        log.warning(f"Error reading seen_jobs: {e} — starting fresh.")
        return {}


def save_seen_ids(seen_dict: dict, path: str = SEEN_JOBS_FILE) -> None:
    """
    Save seen job IDs to JSON file, removing entries older than 7 days.
    """
    now = datetime.now()
    cutoff = now - timedelta(days=MEMORY_DAYS)
    
    # Cleanup old entries
    cleaned = {}
    for jid, ts_iso in seen_dict.items():
        try:
            ts = datetime.fromisoformat(ts_iso)
            if ts > cutoff:
                cleaned[jid] = ts_iso
        except (ValueError, TypeError):
            # If timestamp is invalid, keep it but update it
            cleaned[jid] = now.isoformat()

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, ensure_ascii=False, indent=2)
        log.info(f"Saved {len(cleaned)} seen job IDs (cleaned {len(seen_dict) - len(cleaned)} old ones).")
    except IOError as e:
        log.error(f"Error saving seen_jobs: {e}")


def deduplicate(jobs: list[Job], seen_dict: dict) -> list[Job]:
    """
    Return only jobs whose unique_id is NOT in seen_dict.
    Deduplicates by BOTH title+company AND URL to catch cross-source dupes.
    """
    new_jobs = []
    batch_ids = set()

    for job in jobs:
        uid = job.unique_id
        url_id = getattr(job, 'url_id', '')

        # Check title+company dedup
        if uid in seen_dict or uid in batch_ids:
            continue
        # Check URL dedup
        if url_id and (url_id in seen_dict or url_id in batch_ids):
            continue

        batch_ids.add(uid)
        if url_id:
            batch_ids.add(url_id)
        new_jobs.append(job)

    log.info(f"Dedup: {len(jobs)} total → {len(new_jobs)} new jobs.")
    return new_jobs


def mark_as_seen(jobs: list[Job], seen_dict: dict) -> dict:
    """Add both unique_id and url_id to the seen dict with current timestamp."""
    now_iso = datetime.now().isoformat()
    for job in jobs:
        seen_dict[job.unique_id] = now_iso
        url_id = getattr(job, 'url_id', '')
        if url_id:
            seen_dict[url_id] = now_iso
    return seen_dict
