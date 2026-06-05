"""
Deduplication � v41 (Persistent Fuzzy Dedup)

IMPROVEMENTS v41:
   Fuzzy fingerprints stored in DB and loaded at startup
      same job from different fetchers caught ACROSS RUNS (not just within batch)
   MinHash-inspired token Jaccard similarity (faster than full string compare)
   Threshold tuned: 0.72 (was 0.75) � catches more cross-source dupes
"""

import re
import logging
from datetime import datetime
from models import Job
from config import DAILY_SEND_HOURS, GLOBAL_DEDUP_HOURS, SEEN_JOBS_FILE
from database import JobsDB, get_db

log = logging.getLogger(__name__)

MEMORY_DAYS = 5

_db: JobsDB | None = None
_persistent_fps: list[str] = []   # loaded from DB at startup


def _get_db() -> JobsDB:
    global _db, _persistent_fps
    if _db is None:
        _db = get_db()
        # Load only SENT fingerprints for cross-run fuzzy dedup.
        # Unsent jobs remain eligible in future runs until they are actually delivered.
        _persistent_fps = _db.get_recent_sent_fingerprints(hours=MEMORY_DAYS * 24)
        log.info(f"[dedup] Loaded {len(_persistent_fps)} recently sent fingerprints for cross-run dedup.")
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


def _fuzzy_match(fp1: str, fp2: str, threshold: float = 0.72) -> bool:
    """Token-based Jaccard similarity � fast and effective for job dedup."""
    tokens1 = set(fp1.replace("||", " ").split())
    tokens2 = set(fp2.replace("||", " ").split())
    if not tokens1 or not tokens2:
        return False
    overlap = tokens1 & tokens2
    union   = tokens1 | tokens2
    return len(overlap) / len(union) >= threshold


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


def deduplicate(jobs: list, seen_dict: dict) -> list:
    """
    Four-layer dedup (v42):
      0. Per-source dedup: same url_id from multiple fetchers of same source family
      1. Exact: unique_id + url_id sent in the daily window
      2. Fuzzy batch: fingerprint within current batch
      3. Fuzzy persistent: fingerprint against last 5 days of DB entries
    """
    global _persistent_fps
    db = _get_db()
    new_jobs   = []
    batch_ids: set = set()
    batch_fps: list = []
    # Layer 0: track url_ids per source family to prevent same LinkedIn job
    # appearing from both linkedin_hr_hunter AND linkedin_posts AND linkedin etc.
    source_url_ids: dict = {}

    for job in jobs:
        uid    = job.unique_id
        url_id = getattr(job, "url_id", "")
        source = getattr(job, "source", "")

        # Layer 0: per-source-family dedup (same LinkedIn job ID from different LinkedIn fetchers)
        if url_id and (url_id.startswith("li_job_") or url_id.startswith("li_post_")):
            if url_id in source_url_ids:
                log.debug(f"[dedup] Cross-source dupe (same LinkedIn job): {job.title} � already from {source_url_ids[url_id]}")
                continue
            source_url_ids[url_id] = source

        # Layer 1: exact ID dedup
        if uid in seen_dict or uid in batch_ids:
            continue
        if url_id and (url_id in seen_dict or url_id in batch_ids):
            continue
        dedup_key = getattr(job, "dedup_key", "") or url_id or uid
        if db.was_sent_globally_recently(uid, url_id, dedup_key, hours=GLOBAL_DEDUP_HOURS):
            continue
        if db.was_sent_recently(uid, url_id, lane="any", hours=DAILY_SEND_HOURS):
            continue

        # Layer 2: fuzzy dedup within current batch
        fp = _job_fingerprint(job)
        if any(_fuzzy_match(fp, existing) for existing in batch_fps):
            log.debug(f"[dedup] Fuzzy dupe (batch): {job.title} @ {job.company}")
            continue

        # Layer 3: fuzzy dedup against persistent DB fingerprints
        if any(_fuzzy_match(fp, existing) for existing in _persistent_fps):
            log.debug(f"[dedup] Fuzzy dupe (persistent DB): {job.title} @ {job.company}")
            continue

        batch_ids.add(uid)
        if url_id:
            batch_ids.add(url_id)
        batch_fps.append(fp)
        new_jobs.append(job)

    log.info(f"[dedup] {len(jobs)} total -> {len(new_jobs)} new (4-layer dedup).")
    return new_jobs


def mark_as_seen(jobs: list, seen_dict: dict) -> dict:
    global _persistent_fps
    db = _get_db()
    now_iso = datetime.now().isoformat()
    for job in jobs:
        fp = _job_fingerprint(job)
        db.mark_seen(
            job_key=job.unique_id,
            url_id=getattr(job, "url_id", ""),
            fingerprint=fp,
            title=job.title, company=job.company,
            location=job.location, source=job.source,
            sent=False,
            source_key=getattr(job, "source_key", "") or getattr(job, "source", ""),
            content_type=getattr(job, "content_type", "job_listing"),
            origin_priority=int(getattr(job, "origin_priority", 999) or 999),
        )
        # Do not add unsent jobs to seen_dict or persistent fingerprints:
        # they should stay eligible until sent or stale.
    return seen_dict


def deduplicate_sent(sent_records: list, seen_dict: dict) -> dict:
    """
    Persist successful sends with channel-aware events:
      - per-lane timestamps in jobs table
      - per-channel events in sent_events table (strict 24h channel dedup)
    """
    global _persistent_fps
    db = _get_db()
    now_iso = datetime.now().isoformat()
    for job, lane, channel_key in sent_records:
        fp = _job_fingerprint(job)
        url_id = getattr(job, "url_id", "")
        dedup_key = url_id or job.unique_id
        db.mark_sent(
            job_key=job.unique_id,
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
            job_key=job.unique_id,
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
        seen_dict[job.unique_id] = now_iso
        if url_id:
            seen_dict[url_id] = now_iso
        if fp not in _persistent_fps:
            _persistent_fps.append(fp)
    return seen_dict
