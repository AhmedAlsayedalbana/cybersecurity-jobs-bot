"""
Cybersecurity Jobs Bot — V12 (Professional System)
Orchestrates the full pipeline: Fetch → Filter → Score → Send.
"""

import logging
import os
import time
from datetime import datetime
from sources import ALL_FETCHERS
from models import filter_jobs, Job
from scoring import score_job, sort_by_location_priority
from dedup import load_seen_ids, save_seen_ids, deduplicate, mark_as_seen
from telegram_sender import send_jobs
from classifier import classify_location
import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger("main")

def main():
    start_time = time.time()
    log.info("=" * 60)
    log.info(f"🔐 Professional CyberSec Bot Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    # 1. Load seen jobs
    seen_dict = load_seen_ids()
    
    # 2. Fetch jobs from all sources
    all_raw_jobs = []
    for name, fetcher in ALL_FETCHERS:
        try:
            log.info(f"📡 Fetching: {name}")
            jobs = fetcher()
            all_raw_jobs.extend(jobs)
            log.info(f"   ✓ {name}: {len(jobs)}")
        except Exception:
            # Silent failure for sources to avoid warning spam
            continue

    # 3. Filter jobs
    filtered_jobs = filter_jobs(all_raw_jobs)
    log.info(f"🔍 After filter: {len(filtered_jobs)}")

    # 4. Deduplicate
    new_jobs = deduplicate(filtered_jobs, seen_dict)
    log.info(f"✨ New jobs: {len(new_jobs)}")

    if not new_jobs:
        log.info("🏁 No new jobs to process.")
        return

    # 5. Score and Sort
    scored_jobs = [(j, score_job(j)) for j in new_jobs]
    
    # Sort by location priority (Egypt > Gulf > Global)
    sorted_jobs = sort_by_location_priority(scored_jobs)

    # 6. Distribute to Channels
    # We take top jobs and send them
    final_pool = [item[0] for item in sorted_jobs[:config.MAX_JOBS_PER_RUN]]
    
    if final_pool:
        log.info(f"📨 Sending {len(final_pool)} jobs to Telegram...")
        send_jobs(final_pool)
        
        # 7. Mark as seen and save
        seen_dict = mark_as_seen(final_pool, seen_dict)
        save_seen_ids(seen_dict)
    
    duration = time.time() - start_time
    log.info("=" * 60)
    log.info(f"🏁 DONE in {duration:.1f}s")
    log.info(f"📥 Fetched: {len(all_raw_jobs)} | 🔍 Filtered: {len(filtered_jobs)} | ✨ New: {len(new_jobs)} | 📨 Sent: {len(final_pool)}")
    log.info("=" * 60)

if __name__ == "__main__":
    main()
