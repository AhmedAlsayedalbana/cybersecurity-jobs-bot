"""
Cybersecurity Jobs Telegram Bot — Main entry point.
Pipeline: fetch → filter → dedup → classify+score → split → select → send.
Logic: 20 jobs per run (Dynamic categories) with Egypt/Gulf/Global priority.
"""

import os
import sys
import logging
import time
from datetime import datetime

import config
from sources import ALL_FETCHERS
from models import filter_jobs, Job
from dedup import load_seen_ids, save_seen_ids, deduplicate, mark_as_seen
from telegram_sender import send_jobs
from scoring import score_job, sort_by_location_priority
from classifier import classify_domain

# ─── Professional Logging ────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

def main():
    start_time = time.time()
    log.info("=" * 60)
    log.info(f"🔐 Cybersecurity Jobs Bot — Run Started at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}")
    log.info("=" * 60)

    # Stats tracking
    stats = {
        "fetched": 0,
        "filtered": 0,
        "new": 0,
        "sent": 0,
        "sources": {}
    }

    # ── 1. Load seen IDs ──────────────────────────────────────
    seen = load_seen_ids(config.SEEN_JOBS_FILE)
    is_seed = (
        os.getenv(config.SEED_MODE_ENV, "").lower() in ("1", "true", "yes")
        or len(seen) == 0
    )

    if is_seed:
        log.info("🌱 SEED MODE: registering all jobs as seen (no messages sent).")

    # ── 2. Fetch from all sources ─────────────────────────────
    all_jobs = []
    for name, fetcher in ALL_FETCHERS:
        try:
            log.info(f"📡 Fetching: {name} ...")
            jobs = fetcher()
            all_jobs.extend(jobs)
            stats["sources"][name] = len(jobs)
            log.info(f"   ✓ {name}: {len(jobs)} raw jobs")
        except Exception as e:
            log.error(f"   ✗ {name} failed: {e}")
            stats["sources"][name] = "FAILED"

    stats["fetched"] = len(all_jobs)
    log.info(f"📊 Total raw jobs fetched: {stats["fetched"]}")

    # ── Everything below is protected by finally (always save seen IDs) ──
    try:
        # ── 3. Filter: cybersec keywords + geo ────────────────
        filtered = filter_jobs(all_jobs)
        stats["filtered"] = len(filtered)
        log.info(f"🔍 After cybersec+geo filter: {stats["filtered"]} jobs")

        # ── 4. Deduplicate ────────────────────────────────────
        new_jobs = deduplicate(filtered, seen)
        stats["new"] = len(new_jobs)
        log.info(f"✨ New jobs (after dedup): {stats["new"]}")

        if is_seed:
            # Seed: mark everything seen without sending
            log.info(f"🌱 Marking {len(new_jobs)} jobs as seen...")
            seen = mark_as_seen(new_jobs, seen)
        else:
            # ── 5. Egypt/Gulf-First Priority Selection ──────────
            from classifier import classify_location

            # Separate into priority tiers
            tier1 = []   # Egypt + (SOC or Pentest or Entry)
            tier2 = []   # Egypt (any cyber)
            tier3 = []   # Gulf + (SOC or Pentest or Entry)
            tier4 = []   # Gulf (any cyber)
            tier5 = []   # Remote worldwide

            for job in new_jobs:
                score = score_job(job)
                loc = classify_location(job)
                title = job.title.lower()

                is_soc     = any(k in title for k in ["soc", "security operations", "threat", "incident", "blue team", "dfir", "siem"])
                is_pentest = any(k in title for k in ["pentest", "penetration", "red team", "ethical hack", "bug bounty", "offensive"])
                is_entry   = any(k in title for k in ["junior", "intern", "trainee", "entry level", "entry-level", "fresh grad"])
                is_target  = is_soc or is_pentest or is_entry

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

            # Sort each tier by score descending
            for t in [tier1, tier2, tier3, tier4, tier5]:
                t.sort(key=lambda x: -x[1])

            # 🎯 Target distribution (out of 30):
            #   🇪🇬 Egypt target/entry  → up to 12
            #   🇪🇬 Egypt general       → up to 6
            #   🌙 Gulf target/entry    → up to 7
            #   🌙 Gulf general         → up to 3
            #   🌍 Remote/Global        → fill remaining
            MAX = config.MAX_JOBS_PER_RUN

            def pick(pool, limit):
                return pool[:limit]

            selected  = pick(tier1, 12)
            selected += pick(tier2, 6)
            selected += pick(tier3, 7)
            selected += pick(tier4, 3)

            filled = len(selected)
            if filled < MAX:
                selected += pick(tier5, MAX - filled)

            # If still under MAX, fill from leftovers
            if len(selected) < MAX:
                used = set(id(j) for j, _ in selected)
                leftovers = (
                    tier1[12:] + tier2[6:] + tier3[7:] + tier4[3:]
                )
                leftovers.sort(key=lambda x: -x[1])
                for item in leftovers:
                    if len(selected) >= MAX:
                        break
                    if id(item[0]) not in used:
                        selected.append(item)
                        used.add(id(item[0]))

            # Apply score threshold (with fallback)
            filtered_selection = [(j, s) for j, s in selected if s >= config.SCORE_THRESHOLD]
            if not filtered_selection:
                log.warning("⚠️ No jobs passed threshold — fallback activated.")
                filtered_selection = selected[:10]

            # Guarantee entry-level slots (min 4)
            entry_jobs = [(j, s) for j, s in selected if any(
                k in j.title.lower() for k in ["junior", "intern", "trainee", "entry level", "entry-level", "fresh grad"]
            )]
            guaranteed_entry = entry_jobs[:4]
            others = [item for item in filtered_selection if item[0] not in [ge[0] for ge in guaranteed_entry]]
            combined_selection = guaranteed_entry + others
            final_selection = [j for j, _ in combined_selection][:MAX]

            # Stats log
            eg_count   = sum(1 for j in final_selection if classify_location(j) == "egypt")
            gulf_count = sum(1 for j in final_selection if classify_location(j) == "gulf")
            rem_count  = len(final_selection) - eg_count - gulf_count
            log.info(f"🎯 Final: {len(final_selection)} jobs | 🇪🇬 Egypt:{eg_count} | 🌙 Gulf:{gulf_count} | 🌍 Other:{rem_count}")

            # ── 6. Send ───────────────────────────────────────
            if final_selection:
                log.info(f"📨 Sending {len(final_selection)} jobs to Telegram...")
                sent_count = send_jobs(final_selection)
                stats["sent"] = sent_count
                log.info(f"✅ Sent {sent_count}/{len(final_selection)} jobs successfully.")
            else:
                log.info("ℹ️ No new qualifying jobs this run, even with fallback and entry-level guarantee.")

            # ── 7. Mark SEEN ──────────────────────────────────
            # CRITICAL: We mark ALL new_jobs as seen to avoid re-processing them in the next run
            # This ensures no loss of seen_jobs state.
            seen = mark_as_seen(new_jobs, seen)

    except Exception as e:
        log.exception(f"❌ Unexpected error during processing: {e}")

    finally:
        # ── 8. ALWAYS save seen IDs — even on crash ───────────
        save_seen_ids(seen, config.SEEN_JOBS_FILE)
        elapsed = time.time() - start_time
        
        # Final Professional Stats Summary
        log.info("=" * 60)
        log.info("🏁 RUN SUMMARY")
        log.info(f"⏱️  Time: {elapsed:.1f}s")
        log.info(f"📥 Fetched: {stats["fetched"]}")
        log.info(f"🔍 Filtered: {stats["filtered"]}")
        log.info(f"✨ New: {stats["new"]}")
        log.info(f"📨 Sent: {stats["sent"]}")
        log.info(f"💾 Total Seen: {len(seen)}")
        log.info("=" * 60)


if __name__ == "__main__":
    main()
