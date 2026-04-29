"""
Cybersecurity Jobs Bot — Main entry point — v35
Pipeline: fetch (ASYNC) → filter → dedup → score → tier-select → send.

v35 IMPROVEMENTS:
  ✅ asyncio.gather() parallel fetch — all sources run simultaneously
     (30 min serial → ~3-5 min parallel)
  ✅ SQLite via database.py (dedup.py already updated)
  ✅ Smart fuzzy dedup (cross-source duplicate prevention)
  ✅ Source health report sent to Telegram every morning
"""

import os
import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import config
from sources import ALL_FETCHERS
from models import filter_jobs
from dedup import load_seen_ids, save_seen_ids, deduplicate, mark_as_seen, deduplicate_sent, smart_expire
from database import JobsDB
from telegram_sender import send_jobs
from scoring import score_job_int as score_job, diversity_rerank
from classifier import classify_location

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


# ── Async wrapper: run each blocking fetcher in thread pool ────

async def _fetch_one(executor, name: str, fetcher, stats: dict) -> list:
    """Run a single synchronous fetcher in a thread, return jobs list."""
    loop = asyncio.get_event_loop()
    t0 = time.time()
    try:
        jobs = await loop.run_in_executor(executor, fetcher)
        elapsed = int((time.time() - t0) * 1000)
        stats[name] = len(jobs)
        log.info(f"   ✓ {name}: {len(jobs)} jobs ({elapsed}ms)")
        return jobs
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        log.error(f"   ✗ {name} failed ({elapsed}ms): {e}")
        stats[name] = "FAILED"
        return []


async def fetch_all_async(stats: dict) -> list:
    """Fetch ALL sources concurrently using a thread pool."""
    log.info(f"⚡ Parallel fetch: {len(ALL_FETCHERS)} sources at once...")
    # Max 10 workers: enough to parallelize without hammering the network
    with ThreadPoolExecutor(max_workers=10) as executor:
        tasks = [
            _fetch_one(executor, name, fetcher, stats)
            for name, fetcher in ALL_FETCHERS
        ]
        results = await asyncio.gather(*tasks)

    all_jobs = []
    for batch in results:
        all_jobs.extend(batch)
    return all_jobs


# ── Source health report ────────────────────────────────────────

def _send_health_report(db: JobsDB, source_stats: dict):
    """
    Send a daily health report to Telegram with per-source status.
    Only sends if TELEGRAM_BOT_TOKEN and HEALTH_REPORT_CHAT_ID are set.
    """
    chat_id = os.getenv("HEALTH_REPORT_CHAT_ID", "") or os.getenv("TELEGRAM_GROUP_ID", "")
    token   = config.TELEGRAM_BOT_TOKEN
    if not token or not chat_id:
        return

    health = db.get_source_health(days=7)
    summary = db.get_stats_summary()

    lines = ["📊 *Source Health Report*\n"]
    failed_sources = [s for s, v in source_stats.items() if v == "FAILED"]
    if failed_sources:
        lines.append("❌ *Failed this run:*")
        for s in failed_sources:
            lines.append(f"  • {s}")
        lines.append("")

    lines.append("📈 *7-day stats:*")
    for row in health[:15]:
        icon = "✅" if row["failures"] == 0 else ("⚠️" if row["failures"] < row["runs"] else "❌")
        avg  = f"{row['avg_jobs']:.0f}" if row["avg_jobs"] else "0"
        lines.append(f"  {icon} {row['source']}: {avg} avg jobs, {row['failures']} fails")

    lines.append(f"\n💾 DB: {summary['total_seen']} total seen | {summary['total_sent']} sent")

    text = "\n".join(lines)
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        log.info("📊 Health report sent to Telegram.")
    except Exception as e:
        log.warning(f"Health report failed: {e}")


# ── Main ────────────────────────────────────────────────────────

def main():
    start_time = time.time()
    log.info("=" * 60)
    log.info("🔐 Bot Started at " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 60)

    stats = {"fetched": 0, "filtered": 0, "new": 0, "sent": 0, "sources": {}}

    # 1. Load seen IDs (from SQLite via dedup.py)
    seen = load_seen_ids(config.SEEN_JOBS_FILE)
    is_seed = (
        os.getenv(config.SEED_MODE_ENV, "").lower() in ("1", "true", "yes")
        or len(seen) == 0
    )
    if is_seed:
        log.info("🌱 SEED MODE — no messages sent.")

    # 2. Fetch ALL sources in parallel (asyncio)
    all_jobs = asyncio.run(fetch_all_async(stats["sources"]))
    stats["fetched"] = len(all_jobs)
    log.info(f"📊 Total fetched: {stats['fetched']} jobs")

    # Save source stats to DB for health monitoring
    db = JobsDB()
    db.save_source_stats(stats["sources"])

    try:
        # 3. Filter
        filtered = filter_jobs(all_jobs)
        stats["filtered"] = len(filtered)
        log.info(f"🔍 After filter: {stats['filtered']}")

        # 4. Dedup (exact + fuzzy cross-source)
        new_jobs = deduplicate(filtered, seen)
        stats["new"] = len(new_jobs)
        log.info(f"✨ New jobs: {stats['new']}")

        seen = smart_expire(seen, len(new_jobs))
        if len(new_jobs) == 0:
            new_jobs = deduplicate(filtered, seen)
            stats["new"] = len(new_jobs)
            if new_jobs:
                log.info(f"✨ After smart_expire: {len(new_jobs)} new jobs recovered.")

        if is_seed:
            log.info(f"🌱 Seed: marking {len(new_jobs)} jobs seen")
            seen = mark_as_seen(new_jobs, seen)
        else:
            # 5. Priority tiering — Egypt first, then Gulf, then Rest
            tier1, tier2, tier3, tier4, tier5 = [], [], [], [], []

            for job in new_jobs:
                score = score_job(job)
                loc   = classify_location(job)
                title = job.title.lower()
                from models import _flatten_tags
                tags  = _flatten_tags(job.tags).lower() if job.tags else ""

                is_soc     = any(k in title for k in ["soc", "security operations", "threat", "incident", "blue team", "dfir", "siem"])
                is_pentest = any(k in title for k in ["pentest", "penetration", "red team", "ethical hack", "bug bounty", "offensive"])
                is_entry   = any(k in title for k in ["junior", "intern", "trainee", "entry level", "entry-level", "fresh grad", "graduate"])
                is_gov     = any(k in tags for k in ["government", "egcert", "iti", "itida", "depi", "nti", "nca", "aramco", "g42"])
                is_target  = is_soc or is_pentest or is_entry or is_gov

                if loc == "egypt" and is_target:
                    tier1.append((job, score))
                elif loc == "egypt":
                    tier2.append((job, score))
                elif loc == "gulf" and is_target:
                    tier3.append((job, score))
                elif loc == "gulf":
                    tier4.append((job, score))
                else:
                    tier5.append((job, score))

            for t in [tier1, tier2, tier3, tier4, tier5]:
                t.sort(key=lambda x: -x[1])

            tier1 = diversity_rerank(tier1)
            tier2 = diversity_rerank(tier2)
            tier3 = diversity_rerank(tier3)
            tier4 = diversity_rerank(tier4)
            tier5 = diversity_rerank(tier5)

            log.info(
                f"📊 Tiers — EG-Target:{len(tier1)} EG-Gen:{len(tier2)} "
                f"Gulf-Target:{len(tier3)} Gulf-Gen:{len(tier4)} Other:{len(tier5)}"
            )

            # 6. Build final pool
            POOL_SIZE = config.MAX_JOBS_PER_RUN  # 200
            selected  = tier1[:40]
            selected += tier2[:30]
            selected += tier3[:35]
            selected += tier4[:20]
            if len(selected) < POOL_SIZE:
                selected += tier5[:POOL_SIZE - len(selected)]
            if len(selected) < POOL_SIZE:
                used = set(id(j) for j, _ in selected)
                leftovers = tier1[40:] + tier2[30:] + tier3[35:] + tier4[20:]
                leftovers.sort(key=lambda x: -x[1])
                for item in leftovers:
                    if len(selected) >= POOL_SIZE:
                        break
                    if id(item[0]) not in used:
                        selected.append(item)
                        used.add(id(item[0]))

            final_pool = [j for j, s in selected if s >= config.SCORE_THRESHOLD]
            if not final_pool:
                log.warning("⚠️ No jobs passed threshold — using top 30 fallback")
                final_pool = [j for j, _ in selected[:30]]

            # Guaranteed entry-level
            entry_kws = ["junior", "intern", "trainee", "entry level", "entry-level", "fresh grad"]
            entry_jobs = [j for j in final_pool if any(k in j.title.lower() for k in entry_kws)]
            non_entry  = [j for j in final_pool if j not in entry_jobs]
            final_pool = entry_jobs[:10] + non_entry

            eg_count   = sum(1 for j in final_pool if classify_location(j) == "egypt")
            gulf_count = sum(1 for j in final_pool if classify_location(j) == "gulf")
            rem_count  = len(final_pool) - eg_count - gulf_count

            log.info(
                f"🎯 Pool: {len(final_pool)} jobs"
                f" | 🇪🇬 {eg_count} | 🌙 {gulf_count} | 🌍 {rem_count}"
            )

            # 7. Send
            if final_pool:
                log.info("📨 Sending to Telegram...")
                sent_count, sent_urls = send_jobs(final_pool)
                stats["sent"] = sent_count
                log.info(f"✅ Total sent: {sent_count}")
            else:
                log.info("ℹ️ No qualifying jobs this run.")
                sent_urls = set()

            # 8. Mark seen (SQLite)
            # Mark ALL new jobs as seen — not just sent ones.
            # This prevents jobs that passed the filter but weren't sent (score below threshold,
            # pool size limit, etc.) from reappearing in subsequent runs the same day.
            seen = mark_as_seen(new_jobs, seen)
            log.info(f"💾 Marked {len(new_jobs)} new jobs as seen (all candidates).")
            if sent_urls:
                seen = deduplicate_sent(sent_urls, final_pool, seen)
                log.info(f"💾 Also marked {len(sent_urls)} sent job URLs as seen.")

            # 9. Health report (send once per day — check hour)
            if datetime.now().hour < 10:  # morning run
                _send_health_report(db, stats["sources"])

    except Exception as e:
        log.exception(f"❌ Error: {e}")

    finally:
        save_seen_ids(seen, config.SEEN_JOBS_FILE)
        elapsed = time.time() - start_time
        log.info("=" * 60)
        log.info(f"🏁 DONE in {round(elapsed, 1)}s")
        log.info(f"📥 Fetched: {stats['fetched']}")
        log.info(f"🔍 Filtered: {stats['filtered']}")
        log.info(f"✨ New: {stats['new']}")
        log.info(f"📨 Sent: {stats['sent']}")
        log.info(f"💾 Seen total: {len(seen)}")
        log.info("=" * 60)


if __name__ == "__main__":
    main()
