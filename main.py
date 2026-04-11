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
    log.info(f"🔐 Cybersecurity Jobs Bot — Run Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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
    log.info(f"📊 Total raw jobs fetched: {stats['fetched']}")

    # ── Everything below is protected by finally (always save seen IDs) ──
    try:
        # ── 3. Filter: cybersec keywords + geo ────────────────
        filtered = filter_jobs(all_jobs)
        stats["filtered"] = len(filtered)
        log.info(f"🔍 After cybersec+geo filter: {stats['filtered']} jobs")

        # ── 4. Deduplicate ────────────────────────────────────
        new_jobs = deduplicate(filtered, seen)
        stats["new"] = len(new_jobs)
        log.info(f"✨ New jobs (after dedup): {stats['new']}")

        if is_seed:
            # Seed: mark everything seen without sending
            log.info(f"🌱 Marking {len(new_jobs)} jobs as seen...")
            seen = mark_as_seen(new_jobs, seen)
        else:
            # ── 5. Selection Strategy ───────────────────
            blue_jobs = []
            red_jobs = []
            general_jobs = []

            for job in new_jobs:
                score = score_job(job)
                domain = classify_domain(job)
                
                if domain == "blue":
                    blue_jobs.append((job, score))
                elif domain == "red":
                    red_jobs.append((job, score))
                else:
                    general_jobs.append((job, score))

            # Sort each group by location priority (Egypt > Gulf > Global) and then score
            blue_jobs = sort_by_location_priority(blue_jobs)
            red_jobs = sort_by_location_priority(red_jobs)
            general_jobs = sort_by_location_priority(general_jobs)

            # 🧠 Diversity Logic: Limit same roles and same companies
            def filter_for_diversity(jobs_list, max_per_role=3):
                seen_roles = {}
                seen_companies = set()
                diverse_list = []
                remaining_list = []
                
                for job, score in jobs_list:
                    # Company Diversity
                    if job.company.lower() in seen_companies:
                        remaining_list.append((job, score))
                        continue

                    # Role Diversity
                    title = job.title.lower()
                    role_key = "general"
                    if "soc" in title: role_key = "soc"
                    elif "pentest" in title or "penetration" in title: role_key = "pentest"
                    elif "incident" in title: role_key = "ir"
                    elif "threat" in title: role_key = "threat"
                    elif "cloud" in title: role_key = "cloud"
                    elif "grc" in title or "compliance" in title: role_key = "grc"
                    
                    if seen_roles.get(role_key, 0) < max_per_role:
                        diverse_list.append((job, score))
                        seen_roles[role_key] = seen_roles.get(role_key, 0) + 1
                        seen_companies.add(job.company.lower())
                    else:
                        remaining_list.append((job, score))
                return diverse_list, remaining_list

            # Apply diversity filter
            blue_diverse, blue_rem = filter_for_diversity(blue_jobs, max_per_role=3)
            red_diverse, red_rem = filter_for_diversity(red_jobs, max_per_role=3)
            gen_diverse, gen_rem = filter_for_diversity(general_jobs, max_per_role=3)

            # Final Selection (Target: 7 Blue, 7 Red, 6 General = 20)
            selected_blue = blue_diverse[:7]
            selected_red = red_diverse[:7]
            selected_general = gen_diverse[:6]
            
            # Fallback Pool (if any category is short)
            fallback_pool = sort_by_location_priority(
                blue_diverse[7:] + blue_rem + 
                red_diverse[7:] + red_rem + 
                gen_diverse[6:] + gen_rem
            )
            
            final_selection_with_scores = selected_blue + selected_red + selected_general
            needed = config.MAX_JOBS_PER_RUN - len(final_selection_with_scores)
            if needed > 0:
                final_selection_with_scores += fallback_pool[:needed]

            # 🎯 Dynamic Quality Control: Score >= config.SCORE_THRESHOLD (default 4)
            filtered_selection = [item for item in final_selection_with_scores if item[1] >= config.SCORE_THRESHOLD]

            if not filtered_selection:
                log.warning("⚠️ No jobs passed threshold — fallback activated. Sending top 10 jobs.")
                # Fallback: take top 10 jobs regardless of score
                filtered_selection = final_selection_with_scores[:10]
            
            # 🎓 Guaranteed Entry-Level Jobs
            entry_jobs = [(j, s) for j, s in final_selection_with_scores if any(
                k in j.title.lower() for k in ["junior", "intern", "trainee", "entry level", "entry-level", "fresh grad"]
            )]
            guaranteed_entry = entry_jobs[:3] # Ensure up to 3 entry-level jobs

            # Remove guaranteed entry jobs from filtered_selection to avoid duplicates
            # and ensure they don't take up slots if better jobs are available
            others = [item for item in filtered_selection if item[0] not in [ge[0] for ge in guaranteed_entry]]

            # Combine guaranteed entry jobs with others, then cap
            combined_selection = guaranteed_entry + others
            final_selection = [j for j, _ in combined_selection][:config.MAX_JOBS_PER_RUN]

            log.info(f"🎯 Selection: {len(final_selection)} jobs selected (Threshold: score >= {config.SCORE_THRESHOLD} with fallback & {len(guaranteed_entry)} entry-level guaranteed)")

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
        log.info(f"📥 Fetched: {stats['fetched']}")
        log.info(f"🔍 Filtered: {stats['filtered']}")
        log.info(f"✨ New: {stats['new']}")
        log.info(f"📨 Sent: {stats['sent']}")
        log.info(f"💾 Total Seen: {len(seen)}")
        log.info("=" * 60)


if __name__ == "__main__":
    main()
