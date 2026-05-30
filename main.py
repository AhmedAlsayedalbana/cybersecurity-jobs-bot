"""
Cybersecurity Jobs Bot — Main entry point — v45
Pipeline: fetch (ASYNC) → filter → dedup (3-layer) → score → tier-select → send.

v45 CHANGES (Bot0 → Bot1 migration):
   intelligence/ sub-package (geo, seniority, domain, intent, pool_builder, dedupe)
   greenhouse_expanded source (Big Tech + SaaS + Lever security vendors)
   gulf_monster source (Monster Gulf RSS — UAE + KSA)
   jsearch_enhanced source (JSearch Egypt + Gulf + Remote merged)
   _build_final_pool() now delegates to intelligence.pool_builder (testable)
   Backward-compat: all existing callers unchanged
"""

import os
import asyncio
import logging
import time
from datetime import datetime, timedelta

import config
from sources import SourceSpec, get_source_specs
from models import filter_jobs
from dedup import load_seen_ids, save_seen_ids, deduplicate, mark_as_seen, deduplicate_sent, smart_expire
from database import JobsDB, get_db
from telegram_sender import send_jobs
from scoring import score_job_int as score_job
from intelligence import (
    classify_geo,
    is_entry_level,
    is_remote_job,
)
from intelligence.pool_builder import build_final_pool as _pool_builder_impl

# Legacy import kept for any call-sites that still use job_intelligence directly
from job_intelligence import is_linkedin_job
from sources.http_utils import get_http_metrics, get_proxy_status

# ── Logging setup ──────────────────────────────────────────────────────────
_log_format = os.getenv("LOG_FORMAT", "text")
if _log_format == "json":
    import json as _json

    class _JsonFormatter(logging.Formatter):
        def format(self, record):
            d = {
                "ts":     self.formatTime(record, datefmt="%H:%M:%S"),
                "level":  record.levelname,
                "logger": record.name,
                "msg":    record.getMessage(),
            }
            if record.exc_info:
                d["exc"] = self.formatException(record.exc_info)
            return _json.dumps(d, ensure_ascii=False)

    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
else:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

log = logging.getLogger("main")


# ── Pool builder ───────────────────────────────────────────────────────────

def _build_final_pool(jobs: list) -> list:
    """Delegate to intelligence.pool_builder — single source of truth for pool logic."""
    return _pool_builder_impl(jobs, score_fn=score_job)


# ── Source health gating ───────────────────────────────────────────────────

def _source_enabled_by_health(spec: SourceSpec, db: JobsDB) -> bool:
    if not config.ENABLE_SOURCE_PRIORITY_GATING:
        return True
    return db.can_run_source(spec.key, min_success=config.SOURCE_HEALTH_MIN_SUCCESS)


# ── Async fetch layer ──────────────────────────────────────────────────────

async def _fetch_one(spec: SourceSpec, stats: dict, db: JobsDB) -> list:
    name = spec.name
    fetcher = spec.fetcher
    t0 = time.time()
    try:
        if asyncio.iscoroutinefunction(fetcher):
            jobs = await fetcher()
        else:
            jobs = await asyncio.to_thread(fetcher)
        elapsed = int((time.time() - t0) * 1000)
        stats[spec.key] = len(jobs)
        healthy_success = len(jobs) > 0 or bool(getattr(spec, "allow_empty_runs", False))
        empty_reason = ""
        if len(jobs) == 0 and healthy_success:
            empty_reason = "empty_allowed"
        elif len(jobs) == 0:
            empty_reason = "empty_result"
        db.update_source_health_state(
            spec.key,
            success=healthy_success,
            jobs_count=len(jobs),
            error_code="" if healthy_success else empty_reason,
            auto_disable_threshold=config.SOURCE_AUTO_DISABLE_THRESHOLD,
            quarantine_minutes=config.SOURCE_QUARANTINE_MINUTES,
        )
        log.info(f"    {name}: {len(jobs)} jobs ({elapsed}ms)")
        return jobs
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        log.error(f"    {name} failed ({elapsed}ms): {e}")
        stats[spec.key] = "FAILED"
        db.update_source_health_state(
            spec.key,
            success=False,
            jobs_count=0,
            error_code=type(e).__name__,
            auto_disable_threshold=config.SOURCE_AUTO_DISABLE_THRESHOLD,
            quarantine_minutes=config.SOURCE_QUARANTINE_MINUTES,
        )
        return []


async def fetch_all_async(stats: dict, db: JobsDB) -> list:
    specs = get_source_specs()
    if not specs:
        return []
    log.info(f"✅ Priority fetch plan loaded: {len(specs)} source(s)")

    run_specs = [s for s in specs if _source_enabled_by_health(s, db)]
    skipped = [s.name for s in specs if s not in run_specs]
    if skipped:
        log.info(f"⏭ Health-gated (quarantined): {', '.join(skipped[:8])}")

    all_jobs = []

    # Parallelize all sources — LinkedIn Unified + new Greenhouse batch run concurrently.
    tasks = [_fetch_one(spec, stats, db) for spec in run_specs]
    results = await asyncio.gather(*tasks)

    for spec, batch in zip(run_specs, results):
        # Stamp source metadata for downstream intelligence pipeline.
        for job in batch:
            if not getattr(job, "source_key", ""):
                job.source_key = spec.key
            if not getattr(job, "origin_priority", None):
                job.origin_priority = spec.priority
            if not getattr(job, "content_type", ""):
                job.content_type = "job_listing"
            if not getattr(job, "source", ""):
                job.source = spec.key
        all_jobs.extend(batch)
    return all_jobs


# ── Health report ──────────────────────────────────────────────────────────

def _send_health_report(db: JobsDB, source_stats: dict, proxy_status: dict):
    chat_id = os.getenv("HEALTH_REPORT_CHAT_ID", "") or os.getenv("TELEGRAM_GROUP_ID", "")
    token = config.TELEGRAM_BOT_TOKEN
    if not token or not chat_id:
        return

    health = db.get_source_health(days=7)
    summary = db.get_stats_summary()

    lines = ["🔍 *Source Health Report*\n"]

    failed_sources = [s for s, v in source_stats.items() if v == "FAILED"]
    if failed_sources:
        lines.append("❌ *Failed this run:*")
        for s in failed_sources:
            lines.append(f"  • {s}")
        lines.append("")

    lines.append("📊 *7-day stats:*")
    for row in health[:15]:
        icon = "✅" if row["failures"] == 0 else ("⚠️" if row["failures"] < row["runs"] else "❌")
        avg = f"{row['avg_jobs']:.0f}" if row["avg_jobs"] else "0"
        lines.append(f"  {icon} {row['source']}: {avg} avg jobs, {row['failures']} fails")

    if proxy_status and proxy_status.get("total", 0) > 0:
        lines.append(
            f"\n🌐 *Proxies:* {proxy_status['available']}/{proxy_status['total']} available"
            f" | avg score: {proxy_status.get('avg_score', 0):.0f}"
        )

    lines.append(f"\n💾 DB: {summary['total_seen']} total seen | {summary['total_sent']} sent")

    text = "\n".join(lines)
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        log.info("✅ Health report sent to Telegram.")
    except Exception as e:
        log.warning(f"Health report failed: {e}")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    start_time = time.time()
    log.info("=" * 60)
    log.info("🚀 Bot Started at " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 60)
    config.run_startup_validations()

    stats = {"fetched": 0, "filtered": 0, "new": 0, "sent": 0, "sources": {}}
    db = get_db()

    # 1. Load seen IDs
    seen = load_seen_ids(config.SEEN_JOBS_FILE)

    # Seed mode: if DB is empty, mark seen without sending
    try:
        _db_check = get_db()
        _db_summary = _db_check.get_stats_summary()
        _db_has_history = _db_summary.get("total_seen", 0) > 0
    except Exception:
        _db_summary = {"total_seen": len(seen)}
        _db_has_history = len(seen) > 0

    is_seed = (
        os.getenv(config.SEED_MODE_ENV, "").lower() in ("1", "true", "yes")
        or (len(seen) == 0 and not _db_has_history)
    )
    if is_seed:
        log.info("🌱 SEED MODE — no messages sent.")
    else:
        log.info(f"✅ NORMAL MODE — DB has {_db_summary.get('total_seen', '?')} seen jobs.")

    # 2. Fetch ALL sources (async, parallel)
    all_jobs = asyncio.run(fetch_all_async(stats["sources"], db))
    stats["fetched"] = len(all_jobs)
    log.info(f"📦 Total fetched: {stats['fetched']} jobs")

    # Save source stats & proxy health to DB
    proxy_status = get_proxy_status()
    db.save_source_stats(stats["sources"])
    db.save_proxy_stats(proxy_status)

    if proxy_status.get("total", 0) > 0:
        log.info(
            f"🌐 Proxy health: {proxy_status['available']}/{proxy_status['total']} available"
            f" | banned: {proxy_status['banned']} | avg score: {proxy_status.get('avg_score', 0):.0f}"
        )

    try:
        # 3. Cyber-intent filter (classify_cyber_intent via models.filter_jobs)
        filtered = filter_jobs(all_jobs)
        stats["filtered"] = len(filtered)
        log.info(f"🔍 After filter: {stats['filtered']}")

        # Record training samples for ML filter
        filtered_keys = {getattr(j, "dedup_key", "") for j in filtered}
        train_seen: set[str] = set()
        for job in all_jobs:
            dedup_key = getattr(job, "dedup_key", "") or getattr(job, "url_id", "") or job.unique_id
            if not dedup_key or dedup_key in train_seen:
                continue
            train_seen.add(dedup_key)
            db.record_training_sample(
                dedup_key=dedup_key,
                title=job.title,
                company=job.company,
                location=job.location,
                source=getattr(job, "source_key", "") or job.source,
                content_type=getattr(job, "content_type", "job_listing"),
                description_short=(job.description or "")[:500],
                accepted=dedup_key in filtered_keys,
                reason="filter_pass" if dedup_key in filtered_keys else "filter_reject",
            )
            if len(train_seen) >= 1600:
                break

        # 4. Dedup (3-layer: exact URL + fingerprint + fuzzy Jaccard)
        before_dedup = len(filtered)
        new_jobs = deduplicate(filtered, seen)

        # Hard stale gate (pool_builder handles scoring-based staleness)
        from intelligence.pool_builder import is_stale
        stale_count = sum(1 for j in new_jobs if is_stale(j))
        if stale_count:
            new_jobs = [j for j in new_jobs if not is_stale(j)]
            log.info(f"🗑 Dropped {stale_count} stale jobs (>{config.MAX_JOB_AGE_DAYS}d).")

        stats["new"] = len(new_jobs)
        log.info(f"✨ New jobs: {stats['new']}")
        dedup_dropped = max(0, before_dedup - stats["new"])
        log.info(
            f"🔁 Dedup drop rate: {dedup_dropped}/{before_dedup} "
            f"({(dedup_dropped / max(1, before_dedup)) * 100:.1f}%)"
        )

        seen = smart_expire(seen, len(new_jobs))
        if len(new_jobs) == 0:
            new_jobs = deduplicate(filtered, seen)
            stats["new"] = len(new_jobs)
            if new_jobs:
                log.info(f"♻️ After smart_expire: {len(new_jobs)} new jobs recovered.")

        if is_seed:
            log.info(f"🌱 Seed: marking {len(new_jobs)} jobs seen")
            seen = mark_as_seen(new_jobs, seen)
        else:
            # 5. Build final pool (geo-sorted, ratio-enforced, threshold-gated)
            #    Delegated to intelligence.pool_builder — tested independently.
            final_pool = _build_final_pool(new_jobs)

            # Pool composition summary
            eg_count  = sum(1 for j in final_pool if classify_geo(j) == "egypt")
            ksa_count = sum(1 for j in final_pool if classify_geo(j) == "ksa")
            gulf_count = sum(1 for j in final_pool if classify_geo(j) == "gulf_other")
            rem_count  = sum(1 for j in final_pool if is_remote_job(j))
            entry_count = sum(1 for j in final_pool if is_entry_level(j))
            linkedin_count = sum(1 for j in final_pool if is_linkedin_job(j))

            log.info(
                f"📊 Pool: {len(final_pool)} jobs"
                f" | EG:{eg_count} KSA:{ksa_count} Gulf:{gulf_count}"
                f" Remote:{rem_count} Entry:{entry_count} LinkedIn:{linkedin_count}"
            )

            # 6. Send to Telegram
            if final_pool:
                log.info("📤 Sending to Telegram...")
                sent_count, sent_records = send_jobs(final_pool)
                stats["sent"] = sent_count
                log.info(f"✅ Total sent: {sent_count}")

                sent_keys = {
                    (getattr(j, "dedup_key", "") or getattr(j, "url_id", "") or j.unique_id, ch)
                    for j, _, ch in sent_records
                }
                for job in final_pool:
                    key = getattr(job, "dedup_key", "") or getattr(job, "url_id", "") or job.unique_id
                    for channel in ("candidate_pool",):
                        if (key, channel) in sent_keys:
                            continue
                        db.record_training_sample(
                            dedup_key=key,
                            title=job.title,
                            company=job.company,
                            location=job.location,
                            source=getattr(job, "source_key", "") or job.source,
                            content_type=getattr(job, "content_type", "job_listing"),
                            description_short=(job.description or "")[:500],
                            accepted=True,
                            reason=channel,
                        )
            else:
                log.info("ℹ️ No qualifying jobs this run.")
                sent_records = []

            # 7. Mark seen, dedup sent
            seen = mark_as_seen(new_jobs, seen)
            log.info(f"💾 Marked {len(new_jobs)} new jobs as seen.")
            if sent_records:
                seen = deduplicate_sent(sent_records, seen)

            # 8. Morning health report
            if datetime.now().hour < 10:
                _send_health_report(db, stats["sources"], proxy_status)

            http_metrics = get_http_metrics()
            if http_metrics:
                log.info(
                    "🌐 HTTP telemetry:"
                    f" requests={http_metrics.get('requests', 0)}"
                    f" 429={http_metrics.get('429', 0)}"
                    f" 403={http_metrics.get('403', 0)}"
                    f" errors={http_metrics.get('errors', 0)}"
                )

    except Exception as e:
        log.exception(f"❌ Error: {e}")

    finally:
        save_seen_ids(seen, config.SEEN_JOBS_FILE)
        elapsed = time.time() - start_time
        log.info("=" * 60)
        log.info(f"✅ DONE in {round(elapsed, 1)}s")
        log.info(f"   Fetched:  {stats['fetched']}")
        log.info(f"   Filtered: {stats['filtered']}")
        log.info(f"   New:      {stats['new']}")
        log.info(f"   Sent:     {stats['sent']}")
        log.info(f"   Seen:     {len(seen)}")
        log.info("=" * 60)


if __name__ == "__main__":
    main()
