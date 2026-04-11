"""
Cybersecurity Jobs Telegram Bot — Main entry point.
Pipeline: fetch → filter → dedup → classify+score → split → select → send.
Logic: 15 jobs per run (5 Blue, 5 Red, 5 General) with Egypt/Gulf/Global priority.
"""

import os
import sys
import logging
import time

from config import SEEN_JOBS_FILE, SEED_MODE_ENV
from sources import ALL_FETCHERS
from models import filter_jobs, Job
from dedup import load_seen_ids, save_seen_ids, deduplicate, mark_as_seen
from telegram_sender import send_jobs
from scoring import score_job, sort_by_location_priority
from classifier import classify_domain

# ─── Logging ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


def main():
    start = time.time()
    log.info("=" * 60)
    log.info("🔐 Cybersecurity Jobs Bot — Starting Hourly Elite Run")
    log.info("=" * 60)

    # ── 1. Load seen IDs ──────────────────────────────────────
    seen = load_seen_ids(SEEN_JOBS_FILE)
    is_seed = (
        os.getenv(SEED_MODE_ENV, "").lower() in ("1", "true", "yes")
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
            log.info(f"   ✓ {name}: {len(jobs)} raw jobs")
        except Exception as e:
            log.error(f"   ✗ {name} failed: {e}")

    log.info(f"Total raw jobs fetched: {len(all_jobs)}")

    # ── Everything below is protected by finally (always save seen IDs) ──
    try:
        # ── 3. Filter: cybersec keywords + geo ────────────────
        filtered = filter_jobs(all_jobs)
        log.info(f"After cybersec+geo filter: {len(filtered)} jobs")

        # ── 4. Deduplicate ────────────────────────────────────
        new_jobs = deduplicate(filtered, seen)
        log.info(f"New jobs (after dedup): {len(new_jobs)}")

        if is_seed:
            # Seed: mark everything seen without sending
            log.info(f"🌱 Marking {len(new_jobs)} jobs as seen...")
            seen = mark_as_seen(new_jobs, seen)
        else:
            # ── 5. Elite Selection Strategy ───────────────────
            # Score and classify all new jobs
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

            # 🧠 Diversity Logic: Limit same roles (MAX_PER_ROLE = 2) and same companies
            def filter_for_diversity(jobs_list, max_per_role=2):
                seen_roles = {}
                seen_companies = set()
                diverse_list = []
                remaining_list = []
                
                for job, score in jobs_list:
                    # 🏢 Company Diversity Power Move
                    if job.company.lower() in seen_companies:
                        remaining_list.append((job, score))
                        continue

                    # 🕵️ Role Diversity Power Move
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

            # Apply diversity filter to each category
            blue_diverse, blue_rem = filter_for_diversity(blue_jobs, max_per_role=2)
            red_diverse, red_rem = filter_for_diversity(red_jobs, max_per_role=2)
            gen_diverse, gen_rem = filter_for_diversity(general_jobs, max_per_role=2)

            # Final Selection (Target: 5 Blue, 5 Red, 5 General)
            selected_blue = blue_diverse[:5]
            selected_red = red_diverse[:5]
            selected_general = gen_diverse[:5]
            
            # Fallback Pool (if any category is short)
            fallback_pool = sort_by_location_priority(
                blue_diverse[5:] + blue_rem + 
                red_diverse[5:] + red_rem + 
                gen_diverse[5:] + gen_rem
            )
            
            final_selection_with_scores = selected_blue + selected_red + selected_general
            needed = 15 - len(final_selection_with_scores)
            if needed > 0:
                final_selection_with_scores += fallback_pool[:needed]

            # 🎯 Dynamic Quality Control: Score >= 6
            final_selection_with_scores = [item for item in final_selection_with_scores if item[1] >= 6]
            
            # Final cap at 15
            final_selection = [j for j, s in final_selection_with_scores[:15]]

            log.info(f"Elite Selection: {len(final_selection)} jobs selected (Dynamic Quality Control: score >= 6)")

            # ── 6. Send ───────────────────────────────────────
            if final_selection:
                log.info(f"📨 Sending {len(final_selection)} jobs to Telegram...")
                sent = send_jobs(final_selection)
                log.info(f"✅ Sent {sent}/{len(final_selection)} jobs successfully.")
            else:
                log.info("No new qualifying jobs this run.")

            # Mark ALL new jobs as seen (including skipped ones)
            seen = mark_as_seen(new_jobs, seen)

    except Exception as e:
        log.exception(f"❌ Unexpected error during processing: {e}")

    finally:
        # ── 7. ALWAYS save seen IDs — even on crash ───────────
        save_seen_ids(seen, SEEN_JOBS_FILE)
        elapsed = time.time() - start
        log.info(f"Run complete in {elapsed:.1f}s | Total seen: {len(seen)}")
        log.info("=" * 60)


if __name__ == "__main__":
    main()
