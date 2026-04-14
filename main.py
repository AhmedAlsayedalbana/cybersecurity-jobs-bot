"""
Cybersecurity Jobs Bot — Main entry point.
Pipeline: fetch → filter → dedup → score → tier-select → send.
10 jobs per channel per run. Egypt & Gulf FIRST.
"""

import os
import logging
import time
from datetime import datetime

import config
from sources import ALL_FETCHERS
from models import filter_jobs
from dedup import load_seen_ids, save_seen_ids, deduplicate, mark_as_seen, deduplicate_sent
from telegram_sender import send_jobs
from scoring import score_job
from classifier import classify_location

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


def main():
    start_time = time.time()
    log.info("=" * 60)
    log.info("🔐 Bot Started at " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 60)

    stats = {"fetched": 0, "filtered": 0, "new": 0, "sent": 0, "sources": {}}

    # 1. Load seen IDs
    seen = load_seen_ids(config.SEEN_JOBS_FILE)
    is_seed = (
        os.getenv(config.SEED_MODE_ENV, "").lower() in ("1", "true", "yes")
        or len(seen) == 0
    )
    if is_seed:
        log.info("🌱 SEED MODE — no messages sent.")

    # 2. Fetch
    all_jobs = []
    for name, fetcher in ALL_FETCHERS:
        try:
            log.info("📡 Fetching: " + name)
            jobs = fetcher()
            all_jobs.extend(jobs)
            stats["sources"][name] = len(jobs)
            log.info("   ✓ " + name + ": " + str(len(jobs)))
        except Exception as e:
            log.error("   ✗ " + name + " failed: " + str(e))
            stats["sources"][name] = "FAILED"

    stats["fetched"] = len(all_jobs)
    log.info("📊 Total fetched: " + str(stats["fetched"]))

    try:
        # 3. Filter
        filtered = filter_jobs(all_jobs)
        stats["filtered"] = len(filtered)
        log.info("🔍 After filter: " + str(stats["filtered"]))

        # 4. Dedup
        new_jobs = deduplicate(filtered, seen)
        stats["new"] = len(new_jobs)
        log.info("✨ New jobs: " + str(stats["new"]))

        if is_seed:
            log.info("🌱 Seed: marking " + str(len(new_jobs)) + " jobs seen")
            seen = mark_as_seen(new_jobs, seen)
        else:
            # 5. Priority tiering — Egypt first, then Gulf, then Rest
            tier1 = []  # Egypt + (SOC | Pentest | Entry | Gov)
            tier2 = []  # Egypt (any cyber)
            tier3 = []  # Gulf + (SOC | Pentest | Entry | Gov)
            tier4 = []  # Gulf (any cyber)
            tier5 = []  # Remote / Worldwide

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

            log.info(
                "📊 Tiers — EG-Target:" + str(len(tier1)) +
                " EG-Gen:" + str(len(tier2)) +
                " Gulf-Target:" + str(len(tier3)) +
                " Gulf-Gen:" + str(len(tier4)) +
                " Other:" + str(len(tier5))
            )

            # 6. Build final pool — large enough for all channels × 10
            # Each channel needs up to 10 jobs, 10 channels = up to 100 pool
            POOL_SIZE = config.MAX_JOBS_PER_RUN  # 100

            selected  = tier1[:30]
            selected += tier2[:20]
            selected += tier3[:25]
            selected += tier4[:10]

            if len(selected) < POOL_SIZE:
                selected += tier5[:POOL_SIZE - len(selected)]

            # Backfill from leftovers
            if len(selected) < POOL_SIZE:
                used = set(id(j) for j, _ in selected)
                leftovers = tier1[30:] + tier2[20:] + tier3[25:] + tier4[10:]
                leftovers.sort(key=lambda x: -x[1])
                for item in leftovers:
                    if len(selected) >= POOL_SIZE:
                        break
                    if id(item[0]) not in used:
                        selected.append(item)
                        used.add(id(item[0]))

            # Score threshold filter
            final_pool = [j for j, s in selected if s >= config.SCORE_THRESHOLD]
            if not final_pool:
                log.warning("⚠️ No jobs passed threshold — using top 30 fallback")
                final_pool = [j for j, _ in selected[:30]]

            # Guaranteed entry-level (min 5 in pool)
            entry_kws = ["junior", "intern", "trainee", "entry level", "entry-level", "fresh grad"]
            entry_jobs = [j for j in final_pool if any(k in j.title.lower() for k in entry_kws)]
            non_entry  = [j for j in final_pool if j not in entry_jobs]
            final_pool = entry_jobs[:10] + non_entry

            eg_count   = sum(1 for j in final_pool if classify_location(j) == "egypt")
            gulf_count = sum(1 for j in final_pool if classify_location(j) == "gulf")
            rem_count  = len(final_pool) - eg_count - gulf_count

            log.info(
                "🎯 Pool: " + str(len(final_pool)) + " jobs" +
                " | 🇪🇬 " + str(eg_count) +
                " | 🌙 " + str(gulf_count) +
                " | 🌍 " + str(rem_count)
            )

            # 7. Send — telegram_sender handles 10-per-channel logic
            if final_pool:
                log.info("📨 Sending to Telegram (10 per channel)...")
                sent_count, sent_urls = send_jobs(final_pool)
                stats["sent"] = sent_count
                log.info("✅ Total sent: " + str(sent_count))
            else:
                log.info("ℹ️ No qualifying jobs this run.")
                sent_urls = set()

            # 8. Mark seen — only jobs that were actually sent
            seen = mark_as_seen(new_jobs, seen)  # mark all fetched as seen (prevents re-fetch)
            if sent_urls:
                seen = deduplicate_sent(sent_urls, final_pool, seen)  # also mark sent URLs

    except Exception as e:
        log.exception("❌ Error: " + str(e))

    finally:
        save_seen_ids(seen, config.SEEN_JOBS_FILE)
        elapsed = time.time() - start_time
        log.info("=" * 60)
        log.info("🏁 DONE in " + str(round(elapsed, 1)) + "s")
        log.info("📥 Fetched: " + str(stats["fetched"]))
        log.info("🔍 Filtered: " + str(stats["filtered"]))
        log.info("✨ New: " + str(stats["new"]))
        log.info("📨 Sent: " + str(stats["sent"]))
        log.info("💾 Seen total: " + str(len(seen)))
        log.info("=" * 60)


if __name__ == "__main__":
    main()
