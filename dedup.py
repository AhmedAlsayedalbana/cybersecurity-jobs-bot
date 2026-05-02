"""
Deduplication — v35

CHANGES vs v34:
  ✅ SQLite backend (database.py) instead of seen_jobs.json
  ✅ Backward-compat: still works with dict interface for main.py
  ✅ Smart fuzzy dedup: catches same job from multiple sources (95% similarity)
  ✅ Auto-migrates old seen_jobs.json → SQLite on first run
"""

import json
import os
import re
import logging
from datetime import datetime, timedelta
from models import Job
from config import SEEN_JOBS_FILE
from database import JobsDB

log = logging.getLogger(__name__)

MEMORY_DAYS = 3  # v37: reduced 7→3 — jobs fill in 2-3 days; 7d was blocking 92% of results

_db: JobsDB | None = None


def _get_db() -> JobsDB:
    global _db
    if _db is None:
        _db = JobsDB()
        # Auto-migrate from seen_jobs.json if it exists
        if os.path.exists(SEEN_JOBS_FILE):
            try:
                with open(SEEN_JOBS_FILE, "r", encoding="utf-8") as f:
                    old_data = json.load(f)
                if old_data:
                    if isinstance(old_data, list):
                        now = datetime.now().isoformat()
                        old_data = {k: now for k in old_data}
                    _db.import_seen_dict(old_data)
                    os.rename(SEEN_JOBS_FILE, SEEN_JOBS_FILE + ".migrated")
                    log.info(f"[dedup] Migrated {len(old_data)} entries from JSON to SQLite")
            except Exception as e:
                log.warning(f"[dedup] Migration failed: {e} — starting fresh")
    return _db


# ── Fuzzy fingerprint for smart cross-source dedup ─────────────

def _normalize(text: str) -> str:
    text = text.lower().strip()
    noise = r"\b(inc|ltd|llc|corp|co|the|a|an|of|for|at|in|and)\b"
    text = re.sub(noise, " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _job_fingerprint(job: Job) -> str:
    title   = _normalize(job.title)
    company = _normalize(job.company)
    city    = _normalize(job.location.split(",")[0]) if job.location else ""
    return f"{title}||{company}||{city}"


def _fuzzy_match(fp1: str, fp2: str, threshold: float = 0.85) -> bool:
    tokens1 = set(fp1.split())
    tokens2 = set(fp2.split())
    if not tokens1 or not tokens2:
        return False
    overlap = tokens1 & tokens2
    union   = tokens1 | tokens2
    return len(overlap) / len(union) >= threshold


# ── Public interface (dict-compatible for main.py) ─────────────

def load_seen_ids(path: str = SEEN_JOBS_FILE) -> dict:
    db = _get_db()
    seen = db.to_seen_dict()
    log.info(f"[dedup] Loaded {len(seen)} seen job IDs from SQLite.")
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
    if new_jobs_count > 0:
        return seen_dict
    log.warning("[dedup] smart_expire: 0 new jobs — DB will auto-expire old records next save.")
    return seen_dict


def deduplicate(jobs: list, seen_dict: dict) -> list:
    """
    Two-layer dedup:
      1. Exact: unique_id + url_id
      2. Fuzzy: title+company+city fingerprint (catches cross-source dupes)
    """
    db = _get_db()
    new_jobs   = []
    batch_ids: set = set()
    batch_fps: list = []

    for job in jobs:
        uid    = job.unique_id
        url_id = getattr(job, "url_id", "")

        if uid in seen_dict or uid in batch_ids:
            continue
        if url_id and (url_id in seen_dict or url_id in batch_ids):
            continue
        if db.is_seen(uid, url_id):
            continue

        fp = _job_fingerprint(job)
        if any(_fuzzy_match(fp, existing) for existing in batch_fps):
            log.debug(f"[dedup] Fuzzy dupe: {job.title} @ {job.company}")
            continue

        batch_ids.add(uid)
        if url_id:
            batch_ids.add(url_id)
        batch_fps.append(fp)
        new_jobs.append(job)

    log.info(f"[dedup] {len(jobs)} total -> {len(new_jobs)} new (exact+fuzzy).")
    return new_jobs


def mark_as_seen(jobs: list, seen_dict: dict) -> dict:
    db = _get_db()
    now_iso = datetime.now().isoformat()
    for job in jobs:
        db.mark_seen(
            job_key=job.unique_id,
            url_id=getattr(job, "url_id", ""),
            title=job.title, company=job.company,
            location=job.location, source=job.source,
            sent=False
        )
        seen_dict[job.unique_id] = now_iso
    return seen_dict


def deduplicate_sent(sent_urls: set, jobs: list, seen_dict: dict) -> dict:
    db = _get_db()
    now_iso      = datetime.now().isoformat()
    sent_url_set = set(sent_urls)
    for job in jobs:
        if job.url in sent_url_set:
            db.mark_seen(
                job_key=job.unique_id,
                url_id=getattr(job, "url_id", ""),
                title=job.title, company=job.company,
                location=job.location, source=job.source,
                sent=True
            )
            seen_dict[job.unique_id] = now_iso
    return seen_dict
