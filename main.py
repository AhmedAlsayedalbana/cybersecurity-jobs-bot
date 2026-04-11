"""
Cybersecurity Jobs Telegram Bot — Main entry point.
Pipeline: fetch → filter → dedup → classify+score → split → select → send.
Logic: 30 jobs per run with Egypt/Gulf/Global priority tiers.
"""

import os
import logging
import time
from datetime import datetime

import config
from sources import ALL_FETCHERS
from models import filter_jobs
from dedup import load_seen_ids, save_seen_ids, deduplicate, mark_as_seen
from telegram_sender import send_jobs
from scoring import score_job
from classifier import classify_domain, classify_location

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
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log.info("🔐 Cybersecurity Jobs Bot — Run Started at " + now_str)
    log.info("=" * 60)

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
            log.info("📡 Fetching: " + name + " ...")
            jobs = fetcher()
            all_jobs.extend(jobs)
            stats["sources"][name] = len(jobs)
            log.info("   ✓ " + name + ": " + str(len(jobs)) + " raw jobs")
        except Exception as e:
            log.error("   ✗ " + name + " failed: " + str(e))
            stats["sources"][name] = "FAILED"

    stats["fetched"] = len(all_jobs)
    log.info("📊 Total raw jobs fetched: " + str(stats["fetched"]))

    try:
        # ── 3. Filter ────────────────────────────────────────
        filtered = filter_jobs(all_jobs)
        stats["filtered"] = len(filtered)
        log.info("🔍 After cybersec+geo filter: " + str(stats["filtered"]) + " jobs")

        # ── 4. Deduplicate ───────────────────────────────────
        new_jobs = deduplicate(filtered, seen)
        stats["new"] = len(new_jobs)
        log.info("✨ New jobs (after dedup): " + str(stats["new"]))

        if is_seed:
            log.info("🌱 Marking " + str(len(new_jobs)) + " jobs as seen...")
            seen = mark_as_seen(new_jobs, seen)
        else:
            # ── 5. Egypt/Gulf-First Priority Selection ───────

            tier1 = []   # Egypt + (SOC or Pentest or Entry)
            tier2 = []   # Egypt (any cyber)
            tier3 = []   # Gulf + (SOC or Pentest or Entry)
            tier4 = []   # Gulf (any cyber)
            tier5 = []   # Remote / worldwide

            for job in new_jobs:
                score = score_job(job)
                loc   = classify_location(job)
                title = job.title.lower()

                is_soc     = any(k in title for k in [
                    "soc", "security operations", "threat", "incident",
                    "blue team", "dfir", "siem"
                ])
                is_pentest = any(k in title for k in [
                    "pentest", "penetration", "red team",
                    "ethical hack", "bug bounty", "offensive"
                ])
                is_entry   = any(k in title for k in [
                    "junior", "intern", "trainee",
                    "entry level", "entry-level", "fresh grad"
                ])
                is_target = is_soc or is_pentest or is_entry

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

            MAX = config.MAX_JOBS_PER_RUN

            selected  = tier1[:12]
            selected += tier2[:6]
            selected += tier3[:7]
            selected += tier4[:3]

            if len(selected) < MAX:
                selected += tier5[:MAX - len(selected)]

            if len(selected) < MAX:
                used = set(id(j) for j, _ in selected)
                leftovers = tier1[12:] + tier2[6:] + tier3[7:] + tier4[3:]
                leftovers.sort(key=lambda x: -x[1])
                for item in leftovers:
                    if len(selected) >= MAX:
                        break
                    if id(item[0]) not in used:
                        selected.append(item)
                        used.add(id(item[0]))

            filtered_selection = [(j, s) for j, s in selected if s >= config.SCORE_THRESHOLD]
            if not filtered_selection:
                log.warning("⚠️ No jobs passed threshold — fallback activated.")
                filtered_selection = selected[:10]

            entry_kws = ["junior", "intern", "trainee", "entry level", "entry-level", "fresh grad"]
            entry_jobs = [(j, s) for j, s in selected if any(k in j.title.lower() for k in entry_kws)]
            guaranteed_entry = entry_jobs[:4]

            guaranteed_ids = set(id(ge[0]) for ge in guaranteed_entry)
            others = [item for item in filtered_selection if id(item[0]) not in guaranteed_ids]

            combined_selection = guaranteed_entry + others
            final_selection = [j for j, _ in combined_selection][:MAX]

            eg_count   = sum(1 for j in final_selection if classify_location(j) == "egypt")
            gulf_count = sum(1 for j in final_selection if classify_location(j) == "gulf")
            rem_count  = len(final_selection) - eg_count - gulf_count
            log.info(
                "🎯 Final: " + str(len(final_selection)) + " jobs"
                " | 🇪🇬 Egypt:" + str(eg_count) +
                " | 🌙 Gulf:" + str(gulf_count) +
                " | 🌍 Other:" + str(rem_count)
            )

            # ── 6. Send ──────────────────────────────────────
            if final_selection:
                log.info("📨 Sending " + str(len(final_selection)) + " jobs to Telegram...")
                sent_count = send_jobs(final_selection)
                stats["sent"] = sent_count
                log.info("✅ Sent " + str(sent_count) + "/" + str(len(final_selection)) + " jobs successfully.")
            else:
                log.info("ℹ️ No new qualifying jobs this run.")

            # ── 7. Mark SEEN ─────────────────────────────────
            seen = mark_as_seen(new_jobs, seen)

    except Exception as e:
        log.exception("❌ Unexpected error during processing: " + str(e))

    finally:
        # ── 8. ALWAYS save seen IDs — even on crash ──────────
        save_seen_ids(seen, config.SEEN_JOBS_FILE)
        elapsed = time.time() - start_time

        log.info("=" * 60)
        log.info("🏁 RUN SUMMARY")
        log.info("⏱️  Time: " + str(round(elapsed, 1)) + "s")
        log.info("📥 Fetched:  " + str(stats["fetched"]))
        log.info("🔍 Filtered: " + str(stats["filtered"]))
        log.info("✨ New:      " + str(stats["new"]))
        log.info("📨 Sent:     " + str(stats["sent"]))
        log.info("💾 Total Seen: " + str(len(seen)))
        log.info("=" * 60)


if __name__ == "__main__":
    main()
